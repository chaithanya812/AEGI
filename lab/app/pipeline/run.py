"""The orchestrator — MP-01's job, plus the pipeline wiring.

One request in, one signed, logged verdict out. Every stage emits a trace event as it runs,
which is what the tape on screen is reading; nothing about the animation is on a timer.

Stage order is not arbitrary. Claims are extracted before anything is retrieved, because you
cannot look for evidence for a proposition you have not isolated yet. Evidence is scored
before verdicts, because MP-09 needs to know whether it is reading an audited account or a
press release. And the certificate is signed *last*, over the finished verdict, so what it
attests to is the thing the customer actually saw.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import date

from ..adapters.base import ModelError
from ..adapters.gemini import GeminiAdapter
from ..certs import certificate_payload, signer
from ..contracts import (
    PIPELINE_VERSION,
    Claim,
    EvidenceItem,
    RunResult,
    Support,
)
from ..settings import settings
from ..trace import Tracer, new_request_id, new_trace_id, utcnow_iso
from . import claims as claims_mod
from . import contradiction as contradiction_mod
from . import decision as decision_mod
from . import reliability as reliability_mod
from . import retrieval as retrieval_mod
from . import safe_response as safe_response_mod
from . import temporal as temporal_mod
from . import verdict as verdict_mod

DEFAULT_LAYERS: dict[str, bool] = {
    "retrieval": True,
    "temporal": True,
    "citation": True,
    "contradiction": True,
    "judge": True,
}

#: Concurrency ceiling for per-claim work. Deliberately modest: at 6 a six-claim paragraph
#: fired every judge call inside the same second and tripped the per-minute quota, so three
#: consecutive claims came back UNKNOWN — honest, but for a reason that had nothing to do
#: with the claims. Verifying a paragraph a shade slower beats reporting phantom coverage
#: gaps in front of a client.
_FANOUT = 3

_GENERATION_SYSTEM = (
    "Answer the user's question directly and concisely, in two or three sentences. "
    "Do not add disclaimers about your own limitations."
)


def resolve_layers(requested: dict[str, bool] | None) -> dict[str, bool]:
    layers = dict(DEFAULT_LAYERS)
    for key, value in (requested or {}).items():
        if key in layers:
            layers[key] = bool(value)
    return layers


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


async def generate(prompt: str, *, adapter: GeminiAdapter, tracer: Tracer) -> tuple[str, dict]:
    """Ask the model, unguarded. Thinking is set to minimal deliberately — the artefact
    under test is the model's ordinary first answer, not its most careful one."""
    with tracer.stage("model.generate", "generating answer", module="MP-02") as sink:
        response = await adapter.generate(
            prompt, system=_GENERATION_SYSTEM, thinking="minimal", temperature=0.6
        )
        sink["_message"] = f"answer generated ({len(response.text)} chars)"
        sink["model"] = response.model_id
        sink["output_tokens"] = response.output_tokens
    return response.text, {
        "prompt_tokens": response.prompt_tokens,
        "output_tokens": response.output_tokens,
        "thought_tokens": response.thought_tokens,
    }


async def verify_output(
    output_text: str,
    *,
    prompt: str | None = None,
    mode: str = "verify_given",
    layers: dict[str, bool] | None = None,
    domain: str = "general",
    adapter: GeminiAdapter | None = None,
    tracer: Tracer | None = None,
    token_usage: dict | None = None,
    today: date | None = None,
) -> RunResult:
    cfg = settings()
    layers = resolve_layers(layers)
    tracer = tracer or Tracer(new_trace_id())
    today = today or temporal_mod.reference_clock(cfg.reference_clock)
    usage = dict(token_usage or {})
    degraded_reasons: list[str] = []

    tracer.emit(
        "gateway.accept",
        "request received",
        module="MP-01",
        data={
            "trace_id": tracer.trace_id,
            "chars": len(output_text),
            "reference_clock": today.isoformat(),
        },
    )

    # --- MP-04 / MP-05 ------------------------------------------------------
    with tracer.stage("claims.extract", "extracting claims", module="MP-04") as sink:
        extracted, how, extract_usage = await claims_mod.extract(
            output_text, adapter=adapter, limit=cfg.max_claims
        )
        for key, value in extract_usage.items():
            usage[key] = usage.get(key, 0) + value
        checkable = sum(1 for c in extracted if c.checkable)
        sink["_message"] = (
            f"extracted {len(extracted)} claim(s), {checkable} checkable"
            + ("" if how == "model+grounded" else f" — fell back to {how}")
        )
        sink["method"] = how
        sink["types"] = sorted({c.claim_type.value for c in extracted})
        if how != "model+grounded" and adapter is not None:
            degraded_reasons.append("claim extraction fell back to sentence splitting")

    if not extracted:
        report = reliability_mod.assess(output_text, [])
        decision = decision_mod.decide(report, [], domain=domain, layers_enabled=layers)
        return _finalise(
            tracer=tracer,
            output_text=output_text,
            prompt=prompt,
            mode=mode,
            layers=layers,
            claims=[],
            contradictions=[],
            report=report,
            decision=decision,
            model_id=adapter.model_id if adapter else None,
            usage=usage,
            degraded_reasons=degraded_reasons,
        )

    # --- MP-06 / MP-07 ------------------------------------------------------
    evidence_by_claim: dict[int, list[EvidenceItem]] = {c.claim_index: [] for c in extracted}

    if layers["retrieval"]:
        with tracer.stage("evidence.retrieve", "retrieving evidence", module="MP-06") as sink:
            semaphore = asyncio.Semaphore(_FANOUT)

            async def fetch(claim: Claim) -> tuple[int, list[EvidenceItem], str]:
                if not claim.checkable:
                    return claim.claim_index, [], "skipped"
                async with semaphore:
                    items, retrieval_mode = await retrieval_mod.retrieve_for_claim(
                        claim.text, claim.claim_type, adapter=adapter, today=today
                    )
                return claim.claim_index, items, retrieval_mode

            results = await asyncio.gather(*(fetch(c) for c in extracted))
            modes: set[str] = set()
            for index, items, retrieval_mode in results:
                evidence_by_claim[index] = items
                if retrieval_mode != "skipped":
                    modes.add(retrieval_mode)

            total = sum(len(v) for v in evidence_by_claim.values())
            summary = retrieval_mod.corpus_summary()
            sink["_message"] = (
                f"{total} evidence passage(s) from {summary['documents']} documents "
                f"via {'+'.join(sorted(modes)) or 'none'}"
            )
            sink["retrieval_modes"] = sorted(modes)
            sink["corpus"] = summary
            if "hybrid" not in modes and summary["vectors"]:
                degraded_reasons.append("semantic retrieval unavailable; keyword ranking only")
    else:
        tracer.emit(
            "evidence.retrieve",
            "retrieval switched off for this run — nothing can be verified",
            module="MP-06",
            level="warn",
        )

    # --- MP-10 --------------------------------------------------------------
    contradictions: list[dict] = []
    if layers["contradiction"]:
        with tracer.stage(
            "contradiction.detect", "comparing sources against each other", module="MP-10"
        ) as sink:
            # Per claim, not pooled across the run — see contradiction.detect's docstring.
            groups = [items for items in evidence_by_claim.values() if len(items) > 1]
            report_c = contradiction_mod.detect(groups)
            contradictions = report_c.to_dicts()
            sink["_message"] = (
                f"{len(contradictions)} source conflict(s), worst {report_c.worst}"
                if contradictions
                else "no conflicts between sources"
            )
            if contradictions:
                sink["_level"] = "warn"
                sink["pairs"] = contradictions[:4]

    # --- MP-09 / MP-11 / MP-12 ----------------------------------------------
    with tracer.stage("verdict.assess", "checking each claim", module="MP-09") as sink:
        semaphore = asyncio.Semaphore(_FANOUT)

        async def assess(claim: Claim) -> Claim:
            async with semaphore:
                return await verdict_mod.verify_claim(
                    claim,
                    evidence_by_claim.get(claim.claim_index, []),
                    adapter=adapter,
                    layers=layers,
                    today=today,
                )

        verified = await asyncio.gather(*(assess(c) for c in extracted))
        counts: dict[str, int] = {}
        by_layer: dict[str, int] = {}
        for claim in verified:
            counts[claim.status.value] = counts.get(claim.status.value, 0) + 1
            by_layer[claim.decided_by.value] = by_layer.get(claim.decided_by.value, 0) + 1
        sink["_message"] = ", ".join(f"{v} {k.lower().replace('_', ' ')}" for k, v in counts.items())
        sink["decided_by"] = by_layer
        if any(c.status is Support.CONTRADICTED for c in verified):
            sink["_level"] = "warn"

        # A claim left UNKNOWN because the judge was unreachable is a coverage gap caused by
        # us, not by the claim. Surfacing it separately keeps the two apart — otherwise an
        # outage looks identical to "the corpus has nothing on this", and the reader cannot
        # tell whether the amber tile means "unverified" or "we broke".
        judge_failures = sum(
            1
            for c in verified
            for chk in c.checks
            if chk.name == "entailment" and chk.detail.startswith("judge unavailable")
        )
        if judge_failures:
            sink["judge_failures"] = judge_failures
            sink["_level"] = "warn"
            degraded_reasons.append(
                f"{judge_failures} claim(s) unverified — the entailment judge was unavailable"
            )

    verified_list = list(verified)

    # --- MP-13 --------------------------------------------------------------
    with tracer.stage("reliability.score", "scoring reliability", module="MP-13") as sink:
        report = reliability_mod.assess(output_text, verified_list)
        sink["_message"] = (
            f"{report.band.value} — {report.ledger.supported} verified, "
            f"{report.ledger.contradicted} contradicted, {report.ledger.unknown} unknown"
        )
        sink["band"] = report.band.value
        sink["score"] = report.score

    with tracer.stage("certainty.compare", "comparing stated vs supported confidence") as sink:
        sink["_message"] = (
            f"expressed {report.expressed_confidence.value}, "
            f"supported {report.supported_confidence.value}"
            + (" — FALSE CERTAINTY" if report.false_certainty else "")
        )
        if report.false_certainty:
            sink["_level"] = "warn"

    # --- MP-14 / MP-15 ------------------------------------------------------
    with tracer.stage("decision.apply", "applying decision table", module="MP-15") as sink:
        decision = decision_mod.decide(
            report, verified_list, domain=domain, layers_enabled=layers
        )
        sink["_message"] = (
            f"{decision.outcome.value} (risk {decision.risk.value}) under rule {decision.rule_id}"
        )
        sink["rule"] = decision.rule_id
        sink["table_version"] = decision.table_version

    return _finalise(
        tracer=tracer,
        output_text=output_text,
        prompt=prompt,
        mode=mode,
        layers=layers,
        claims=verified_list,
        contradictions=contradictions,
        report=report,
        decision=decision,
        model_id=adapter.model_id if adapter else None,
        usage=usage,
        degraded_reasons=degraded_reasons,
    )


def _finalise(
    *,
    tracer: Tracer,
    output_text: str,
    prompt: str | None,
    mode: str,
    layers: dict[str, bool],
    claims: list[Claim],
    contradictions: list[dict],
    report,
    decision,
    model_id: str | None,
    usage: dict,
    degraded_reasons: list[str],
) -> RunResult:
    created_at = utcnow_iso()
    output_hash = sha256_hex(output_text)

    with tracer.stage("response.compose", "composing the message", module="MP-16") as sink:
        message = safe_response_mod.compose(
            report=report, decision=decision, claims=claims, output_text=output_text
        )
        sink["_message"] = "nothing to warn about" if message is None else "explanation written"

    claim_dicts = [c.model_dump(mode="json") for c in claims]

    with tracer.stage("certificate.sign", "signing the verdict") as sink:
        payload = certificate_payload(
            trace_id=tracer.trace_id,
            request_id=tracer.trace_id.replace("trace_", "req_"),
            output_text=output_text,
            output_sha256=output_hash,
            model_id=model_id,
            pipeline_version=PIPELINE_VERSION,
            layers_enabled=layers,
            band=report.band.value,
            score=report.score,
            ledger=report.ledger.model_dump(),
            decision=decision.model_dump(mode="json"),
            claims=claim_dicts,
            expressed_confidence=report.expressed_confidence.value,
            supported_confidence=report.supported_confidence.value,
            false_certainty=report.false_certainty,
            degraded=bool(degraded_reasons),
            created_at=created_at,
        )
        signing = signer()
        certificate = signing.sign(tracer.trace_id, payload)
        sink["_message"] = f"signed ed25519 · key {signing.key_id}"
        sink["key_id"] = signing.key_id
        if signing.ephemeral:
            sink["_level"] = "warn"
            sink["_message"] += " (ephemeral key — SIGNING_SEED not configured)"

    tracer.emit(
        "trace.complete",
        f"verification complete in {tracer.elapsed_ms} ms",
        module="MP-24",
        data={"trace_id": tracer.trace_id},
    )

    return RunResult(
        trace_id=tracer.trace_id,
        request_id=new_request_id(),
        created_at=created_at,
        mode=mode,
        prompt=prompt,
        output_text=output_text,
        output_sha256=output_hash,
        model_id=model_id,
        pipeline_version=PIPELINE_VERSION,
        layers_enabled=layers,
        claims=claims,
        contradictions=contradictions,
        reliability=report,
        decision=decision,
        safe_response=message,
        events=tracer.events,
        certificate=certificate,
        latency_ms=tracer.elapsed_ms,
        token_usage=usage,
        degraded=bool(degraded_reasons),
        degraded_reason="; ".join(degraded_reasons) or None,
    )


async def generate_and_verify(
    prompt: str,
    *,
    layers: dict[str, bool] | None = None,
    domain: str = "general",
    adapter: GeminiAdapter | None = None,
) -> RunResult:
    tracer = Tracer(new_trace_id())
    tracer.emit("gateway.accept", "request received", module="MP-01", data={"prompt_chars": len(prompt)})

    if adapter is None:
        raise ModelError("no model configured; cannot generate", retryable=False)

    text, usage = await generate(prompt, adapter=adapter, tracer=tracer)
    return await verify_output(
        text,
        prompt=prompt,
        mode="generate",
        layers=layers,
        domain=domain,
        adapter=adapter,
        tracer=tracer,
        token_usage=usage,
    )
