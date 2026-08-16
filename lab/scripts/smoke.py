"""End-to-end smoke test.

Runs a fixed set of outputs through the pipeline and prints the verdicts. Works with or
without a Gemini key — which is the point of the test: with the key absent, everything it
still catches is exactly the part of the product that does not depend on a model.

    python scripts/smoke.py
    python scripts/smoke.py --no-store    # skip the audit-log write
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.certs import signer, verify_certificate  # noqa: E402
from app.pipeline import run as run_mod  # noqa: E402
from app.pipeline.retrieval import corpus_summary  # noqa: E402
from app.settings import settings  # noqa: E402
from app.store import store  # noqa: E402

CASES: list[tuple[str, str, str, str]] = [
    (
        "future-event",
        "general",
        "Argentina won the 2027 FIFA World Cup, beating Brazil 3-1 in the final.",
        "CONTRADICTED by date arithmetic — deterministic, no model",
    ),
    (
        "figure-mismatch",
        "financial",
        "Northwind Systems reported FY2025 revenue of GBP 4.2 billion, per the audited board pack.",
        "CONTRADICTED by figure comparison — deterministic, no model",
    ),
    (
        "eiffel-mixed",
        "general",
        "The Eiffel Tower was built in 1789 by Napoleon Bonaparte as a monument to the French "
        "Revolution, and it remains the tallest structure in Europe at over 500 meters. "
        "but i think burj kahalifa is the tallest tower",
        "height claim CONTRADICTED numerically; final hedged clause NOT scored as wrong",
    ),
    (
        "not-checkable",
        "general",
        "my name might be mark . tom and jerry is disny show",
        "sentence 1 NOT_APPLICABLE (regression guard); sentence 2 a real misattribution",
    ),
    (
        "fabricated-citation",
        "legal",
        "The indemnity cap is set out in MAT-NW-XYZ-9999 at clause 88.7.",
        "citation unresolvable — deterministic",
    ),
    (
        "clean",
        "general",
        "Photosynthesis converts light energy into chemical energy, consuming carbon dioxide "
        "and water and releasing oxygen.",
        "SUPPORTED where the judge is available; PARTIAL without it",
    ),
]


async def main() -> int:
    cfg = settings()
    use_store = "--no-store" not in sys.argv

    print("=" * 78)
    print(f"model configured   : {cfg.has_model}  ({cfg.model_id if cfg.has_model else 'none'})")
    print(f"audit log          : {cfg.has_store and use_store}")
    sig = signer()
    print(f"signing key        : {sig.key_id}{'  (EPHEMERAL)' if sig.ephemeral else ''}")
    print(f"corpus             : {json.dumps(corpus_summary())}")
    print("=" * 78)

    from app.main import adapter

    failures = 0
    for name, domain, text, expectation in CASES:
        result = await run_mod.verify_output(
            text, domain=domain, adapter=adapter(), mode="verify_given"
        )
        rel = result.reliability
        led = rel.ledger

        print()
        print(f"[{name}]  domain={domain}")
        print(f"  expect : {expectation}")
        print(f"  text   : {text[:96]}{'...' if len(text) > 96 else ''}")
        print(
            f"  BAND   : {rel.band.value}  score={rel.score}  "
            f"decision={result.decision.outcome.value}  risk={result.decision.risk.value}  "
            f"rule={result.decision.rule_id}"
        )
        print(
            f"  ledger : sup={led.supported} part={led.partially_supported} "
            f"unk={led.unknown} unsup={led.unsupported} contra={led.contradicted} "
            f"n/a={led.not_applicable}"
        )
        print(
            f"  certain: expressed={rel.expressed_confidence.value} "
            f"supported={rel.supported_confidence.value} "
            f"false_certainty={rel.false_certainty}"
        )
        for claim in result.claims:
            evidence = (
                f"{claim.evidence[0].doc_id} p{claim.evidence[0].page}"
                if claim.evidence
                else "no evidence"
            )
            print(
                f"    #{claim.claim_index} [{claim.claim_type.value:<12}] "
                f"{claim.status.value:<20} via {claim.decided_by.value:<14} {evidence}"
            )
            print(f"        \"{claim.text[:88]}\"")
            if claim.reasoning:
                print(f"        -> {claim.reasoning[:180]}")
        if result.contradictions:
            for pair in result.contradictions[:2]:
                print(f"  MP-10  : {pair['detail'][:150]}")
        if result.degraded_reason:
            print(f"  degraded: {result.degraded_reason}")

        cert = result.certificate.model_dump(mode="json") if result.certificate else None
        if cert is None:
            print("  CERT   : MISSING")
            failures += 1
        else:
            valid, detail = verify_certificate(cert)
            print(f"  CERT   : valid={valid}  {detail}")
            if not valid:
                failures += 1
            # Tamper check: the signature must fail once the payload is altered. Mutating
            # the score rather than the band, because setting the band to VERIFIED is a
            # no-op on a run that was already VERIFIED — which silently passed the test.
            tampered = json.loads(json.dumps(cert))
            tampered["payload"]["verdict"]["score"] = int(cert["payload"]["verdict"]["score"]) + 1
            tampered["payload"]["verdict"]["band"] = "VERIFIED"
            still_valid, _ = verify_certificate(tampered)
            print(f"  TAMPER : rejected={not still_valid}")
            if still_valid:
                failures += 1

        if use_store and cfg.has_store:
            ok, error = await store().persist(result.model_dump(mode="json"))
            print(f"  LOGGED : {ok}{'  ' + str(error) if error else ''}")
            if not ok:
                failures += 1

    if use_store and cfg.has_store:
        print()
        print(f"log counters: {json.dumps(await store().counters())}")

    await store().aclose()
    from app.main import _adapter

    if _adapter is not None:
        await _adapter.aclose()

    print()
    print("=" * 78)
    print(f"failures: {failures}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
