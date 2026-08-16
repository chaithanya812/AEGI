"""MP-09 — Hallucination and Unsupported Claim Detector.

Five values, not a boolean, because "we found nothing" and "we found the opposite" demand
completely different responses: one is a shrug, the other is an alarm. Plus
NOT_APPLICABLE for claims that carry no falsifiable assertion — see contracts.py.

**Order of authority.** Deterministic checks run first and, when they fail, they settle the
verdict without consulting the model. The judge is asked only about prose that arithmetic
cannot reach. This is what makes the answer to "your verifier is the same model that
hallucinated" a real answer: for the failures that matter most — a future-dated event, a
figure that contradicts its source, a citation pointing at nothing — no model opinion is
involved, and `decided_by` records which layer ruled so the claim can be audited.

**Absence of evidence is reported, not filled in.** A claim with no retrievable evidence
returns UNKNOWN. It never becomes UNSUPPORTED-as-if-refuted, and it is shown amber rather
than red. Guessing here is the failure that destroys a validator's credibility, because the
user can tell.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ..adapters.base import ModelError
from ..adapters.gemini import GeminiAdapter
from ..contracts import (
    CheckOutcome,
    CheckResult,
    Claim,
    DecidedBy,
    EvidenceItem,
    Support,
)
from . import citation as citation_mod
from . import temporal as temporal_mod
from .claims import non_checkable_reason

_JUDGE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {
            "type": "string",
            "enum": [
                "SUPPORTED",
                "PARTIALLY_SUPPORTED",
                "UNSUPPORTED",
                "CONTRADICTED",
                "UNKNOWN",
            ],
        },
        "reasoning": {
            "type": "string",
            "description": "One or two sentences. State what the evidence says, not what you believe.",
        },
        "decisive_quote": {
            "type": "string",
            "description": "Verbatim sentence from the evidence that settles it, or empty.",
        },
        "confidence": {"type": "number"},
    },
    "required": ["status", "reasoning"],
}

_JUDGE_SYSTEM = """You are an entailment checker, not an assistant. You are given a CLAIM and
EVIDENCE drawn from a fixed corpus. Decide only whether the evidence supports the claim.

Rules, in order:
- Use ONLY the evidence provided. Your own knowledge is not evidence and must not be used.
- SUPPORTED: the evidence directly entails the claim.
- PARTIALLY_SUPPORTED: the evidence supports part of the claim, or supports it with an
  important qualification the claim omits.
- CONTRADICTED: the evidence directly asserts something incompatible with the claim.
- UNSUPPORTED: the evidence is on-topic but does not establish the claim.
- UNKNOWN: the evidence does not address the claim at all.
- If the evidence explicitly warns that a common reading is an error, and the claim makes
  exactly that error, the verdict is CONTRADICTED.
- `decisive_quote` must be copied verbatim from the evidence, or left empty.
- Never say a claim is true because it sounds plausible. Absence of evidence is UNKNOWN."""


def _format_evidence(evidence: list[EvidenceItem]) -> str:
    blocks = []
    for i, item in enumerate(evidence, 1):
        blocks.append(
            f"[{i}] {item.doc_title} ({item.doc_id}) — {item.section}, page {item.page}\n"
            f"{item.quote}"
        )
    return "\n\n".join(blocks)


async def judge(
    claim_text: str, evidence: list[EvidenceItem], *, adapter: GeminiAdapter
) -> tuple[Support, str, str, float]:
    prompt = (
        f"CLAIM:\n{claim_text}\n\n"
        f"EVIDENCE:\n{_format_evidence(evidence)}\n\n"
        f"Decide whether the evidence supports the claim."
    )
    parsed, _response = await adapter.generate_json(
        prompt, _JUDGE_SCHEMA, system=_JUDGE_SYSTEM, thinking="medium", temperature=0.0
    )
    raw_status = str((parsed or {}).get("status") or "UNKNOWN").upper()
    try:
        status = Support(raw_status)
    except ValueError:
        status = Support.UNKNOWN
    reasoning = str((parsed or {}).get("reasoning") or "").strip()
    quote = str((parsed or {}).get("decisive_quote") or "").strip()
    try:
        confidence = float((parsed or {}).get("confidence") or 0.6)
    except (TypeError, ValueError):
        confidence = 0.6
    return status, reasoning, quote, max(0.0, min(1.0, confidence))


async def verify_claim(
    claim: Claim,
    evidence: list[EvidenceItem],
    *,
    adapter: GeminiAdapter | None,
    layers: dict[str, bool],
    today: date,
) -> Claim:
    """Fills in status / decided_by / reasoning / checks on the claim, in place."""

    # --- non-checkable: settled before anything else -------------------------
    if not claim.checkable:
        claim.status = Support.NOT_APPLICABLE
        claim.decided_by = DecidedBy.NONE
        claim.reasoning = non_checkable_reason(claim)
        claim.confidence = 1.0
        claim.checks = [
            CheckResult(
                name="classification",
                module="MP-05",
                outcome=CheckOutcome.SKIP,
                detail=f"classified {claim.claim_type.value}; nothing falsifiable to check",
                deterministic=True,
            )
        ]
        return claim

    claim.evidence = evidence
    checks: list[CheckResult] = []

    # --- MP-12 temporal: deterministic, highest authority -------------------
    if layers.get("temporal", True):
        temporal_checks, decisive = temporal_mod.validate(claim.text, evidence, today=today)
        checks.extend(temporal_checks)
        if decisive is not None and decisive.outcome is CheckOutcome.FAIL:
            if decisive.superseding_doc:
                # Stale rather than false: keep it amber unless a figure also disagrees.
                claim.status = Support.PARTIALLY_SUPPORTED
                claim.decided_by = DecidedBy.DETERMINISTIC
                claim.reasoning = decisive.detail
                claim.confidence = 0.85
                claim.checks = checks
                # Fall through to the citation check — a stale source *and* a wrong figure
                # is a contradiction, not merely staleness.
            else:
                claim.status = Support.CONTRADICTED
                claim.decided_by = DecidedBy.DETERMINISTIC
                claim.reasoning = decisive.detail
                claim.confidence = 0.99
                claim.checks = checks
                return claim

    # --- MP-11 citation and figure agreement: deterministic -----------------
    if layers.get("citation", True):
        citation_checks, decisive_detail = citation_mod.validate(claim.text, evidence)
        checks.extend(citation_checks)
        if decisive_detail:
            claim.status = Support.CONTRADICTED
            claim.decided_by = DecidedBy.DETERMINISTIC
            claim.reasoning = decisive_detail
            claim.confidence = 0.97
            claim.checks = checks
            return claim

    # --- no evidence: say so, do not guess ----------------------------------
    if not evidence:
        checks.append(
            CheckResult(
                name="evidence.retrieval",
                module="MP-06",
                outcome=CheckOutcome.INCONCLUSIVE,
                detail="no supporting or refuting material found in the corpus",
                deterministic=True,
            )
        )
        claim.status = Support.UNKNOWN
        claim.decided_by = DecidedBy.DETERMINISTIC
        claim.reasoning = (
            "Nothing in the indexed corpus addresses this claim. It is reported as unknown "
            "rather than judged, because absence of evidence is not evidence of error."
        )
        claim.confidence = 0.9
        claim.checks = checks
        return claim

    # --- MP-09 entailment: the fuzzy remainder ------------------------------
    if adapter is None or not layers.get("judge", True):
        # Judge disabled by the rig, or no model configured. Report what the deterministic
        # layer established and no more; never upgrade to SUPPORTED on silence.
        if claim.status is Support.UNKNOWN:
            claim.status = Support.PARTIALLY_SUPPORTED if evidence else Support.UNKNOWN
            claim.decided_by = DecidedBy.GROUNDED
            claim.reasoning = (
                "Evidence was retrieved and the deterministic checks found no conflict, but "
                "entailment checking is switched off, so support is not established."
            )
            claim.confidence = 0.5
        claim.checks = checks
        return claim

    try:
        status, reasoning, quote, confidence = await judge(claim.text, evidence, adapter=adapter)
    except ModelError as exc:
        checks.append(
            CheckResult(
                name="entailment",
                module="MP-09",
                outcome=CheckOutcome.INCONCLUSIVE,
                detail=f"judge unavailable: {exc}",
                deterministic=False,
            )
        )
        claim.status = Support.UNKNOWN
        claim.decided_by = DecidedBy.DETERMINISTIC
        claim.reasoning = (
            "The entailment check could not be completed, so this claim is unverified. "
            "It is not being reported as correct."
        )
        claim.confidence = 0.3
        claim.checks = checks
        return claim

    outcome = {
        Support.SUPPORTED: CheckOutcome.PASS,
        Support.PARTIALLY_SUPPORTED: CheckOutcome.INCONCLUSIVE,
        Support.UNSUPPORTED: CheckOutcome.FAIL,
        Support.CONTRADICTED: CheckOutcome.FAIL,
        Support.UNKNOWN: CheckOutcome.INCONCLUSIVE,
    }.get(status, CheckOutcome.INCONCLUSIVE)

    checks.append(
        CheckResult(
            name="entailment",
            module="MP-09",
            outcome=outcome,
            detail=reasoning or f"judged {status.value}",
            deterministic=False,
        )
    )

    # A prior deterministic staleness finding is not overwritten by a judge that read the
    # superseded text and found it self-consistent — which it will, because it is.
    if claim.decided_by is DecidedBy.DETERMINISTIC and claim.status is Support.PARTIALLY_SUPPORTED:
        if status is Support.CONTRADICTED:
            claim.status = Support.CONTRADICTED
            claim.reasoning = f"{claim.reasoning} The evidence also contradicts it directly: {reasoning}"
            claim.decided_by = DecidedBy.GROUNDED
        claim.checks = checks
        return claim

    claim.status = status
    claim.decided_by = DecidedBy.GROUNDED if quote else DecidedBy.JUDGE
    claim.reasoning = reasoning
    claim.confidence = confidence
    if quote:
        for item in claim.evidence:
            if quote[:60] in item.quote:
                item.relevance = max(item.relevance, 0.99)
                break
    claim.checks = checks
    return claim
