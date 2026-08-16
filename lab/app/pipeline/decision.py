"""MP-14 — Risk Classification, and MP-15 — Decision Engine.

Both are deliberately boring code. MP-15's own specification says a decision table, not a
model, and gives the reason: this is the module a regulator asks you to explain line by
line, and "the neural network decided" is not an answer that survives that meeting.

So the table below is literal, ordered, versioned, and every decision records the full set
of inputs that produced it — which is what makes a past decision reproducible rather than
merely logged.

**One safeguard worth reading twice.** A BLOCK requires a deterministic or grounded basis.
If the *only* thing condemning an output is the judge model's opinion, the outcome is REVIEW
rather than BLOCK. This is the structural version of the promise the whole lab rests on: an
LLM is never the sole authority for the strongest action the system can take. Rule
``R-JUDGE-ONLY`` is where that is enforced, and it is the rule to point at when someone asks
what stops the verifier hallucinating too.

Risk is separate from reliability because **context matters as much as the score.** One
unsupported claim in a meeting summary is MEDIUM. The identical claim in a dosage
recommendation is CRITICAL. Same reliability report, different risk, which is exactly why
MP-14 is not folded into MP-13.
"""

from __future__ import annotations

from typing import Any, Callable

from ..contracts import (
    Band,
    Claim,
    Confidence,
    Decision,
    DecidedBy,
    Outcome,
    ReliabilityReport,
    Risk,
    Support,
)

DECISION_TABLE_VERSION = "2026.08.16-1"

#: MP-14 sensitivity multipliers. The hospital and the law firm ship different tables;
#: this is the shape of that configuration, not a claim about the right values.
DOMAIN_SENSITIVITY: dict[str, float] = {
    "general": 1.0,
    "financial": 1.3,
    "legal": 1.4,
    "clinical": 1.6,
}


def classify_risk(
    report: ReliabilityReport, claims: list[Claim], *, domain: str = "general"
) -> tuple[Risk, list[str]]:
    ledger = report.ledger
    factors: list[str] = []

    base = 0.0
    if ledger.contradicted:
        base += 3.0 + 0.5 * (ledger.contradicted - 1)
        factors.append(f"{ledger.contradicted} contradicted claim(s)")
    if ledger.unsupported:
        base += 1.5
        factors.append(f"{ledger.unsupported} unsupported claim(s)")
    if ledger.unknown:
        base += 0.5
        factors.append(f"{ledger.unknown} claim(s) with no evidence either way")
    if report.false_certainty:
        base += 1.5
        factors.append("false certainty: stated confidently, not supported by evidence")
    if report.source_quality and report.source_quality < 0.6:
        base += 0.5
        factors.append("supporting sources are low-authority")
    if report.recency and report.recency < 0.3:
        base += 0.5
        factors.append("supporting sources are old")

    multiplier = DOMAIN_SENSITIVITY.get(domain, 1.0)
    scaled = base * multiplier
    if multiplier != 1.0 and base > 0:
        factors.append(f"{domain} deployment sensitivity ×{multiplier}")

    if scaled >= 4.5:
        risk = Risk.CRITICAL
    elif scaled >= 2.5:
        risk = Risk.HIGH
    elif scaled >= 1.0:
        risk = Risk.MEDIUM
    else:
        risk = Risk.LOW

    if not factors:
        factors.append("no risk factors triggered")
    return risk, factors


def _has_hard_basis(claims: list[Claim]) -> bool:
    """True when at least one damning verdict rests on arithmetic or a fetched source span,
    rather than on the judge model alone."""
    return any(
        c.status in (Support.CONTRADICTED, Support.UNSUPPORTED)
        and c.decided_by in (DecidedBy.DETERMINISTIC, DecidedBy.GROUNDED)
        for c in claims
    )


def _judge_only_condemnation(claims: list[Claim]) -> bool:
    condemned = [c for c in claims if c.status in (Support.CONTRADICTED, Support.UNSUPPORTED)]
    return bool(condemned) and all(c.decided_by is DecidedBy.JUDGE for c in condemned)


#: (rule_id, predicate, outcome, note). First match wins. Order is the policy.
_RULES: list[tuple[str, Callable[[ReliabilityReport, Risk, list[Claim]], bool], Outcome, str]] = [
    (
        "R-EMPTY",
        lambda r, k, c: not c,
        Outcome.REVIEW,
        "nothing could be extracted from this output, so nothing was verified",
    ),
    (
        "R-JUDGE-ONLY",
        lambda r, k, c: _judge_only_condemnation(c),
        Outcome.REVIEW,
        "the only basis for rejecting this output is the judge model's opinion; a human decides",
    ),
    (
        "R-CRITICAL-HARD",
        lambda r, k, c: k is Risk.CRITICAL and _has_hard_basis(c),
        Outcome.BLOCK,
        "critical risk with a deterministic or source-grounded contradiction",
    ),
    (
        "R-CONTRA-FALSE-CERT",
        lambda r, k, c: r.ledger.contradicted > 0 and r.false_certainty and _has_hard_basis(c),
        Outcome.BLOCK,
        "confidently stated and demonstrably contradicted by its own sources",
    ),
    (
        "R-CONTRA-HARD",
        lambda r, k, c: r.ledger.contradicted > 0 and _has_hard_basis(c),
        Outcome.BLOCK,
        "at least one claim is contradicted on deterministic grounds",
    ),
    (
        "R-CONTRA-SOFT",
        lambda r, k, c: r.ledger.contradicted > 0,
        Outcome.REVIEW,
        "a contradiction was found but not on deterministic grounds",
    ),
    (
        "R-HIGH-RISK",
        lambda r, k, c: k is Risk.HIGH,
        Outcome.REVIEW,
        "high risk without a hard contradiction — routed to a human",
    ),
    (
        "R-UNSUPPORTED",
        lambda r, k, c: r.ledger.unsupported > 0,
        Outcome.ALLOW_WITH_WARNING,
        "some claims are not supported by the evidence found",
    ),
    (
        "R-FALSE-CERT",
        lambda r, k, c: r.false_certainty,
        Outcome.ALLOW_WITH_WARNING,
        "stated more confidently than the evidence supports",
    ),
    (
        "R-COVERAGE",
        lambda r, k, c: r.ledger.unknown > 0 or r.ledger.partially_supported > 0,
        Outcome.ALLOW_WITH_WARNING,
        "parts of this output could not be verified against the corpus",
    ),
    (
        "R-NOTHING-CHECKABLE",
        lambda r, k, c: r.ledger.checkable_total == 0,
        Outcome.ALLOW,
        "no falsifiable claims in this output",
    ),
    (
        "R-CLEAN",
        lambda r, k, c: r.band is Band.VERIFIED,
        Outcome.ALLOW,
        "every checkable claim is supported by evidence",
    ),
]


def decide(
    report: ReliabilityReport,
    claims: list[Claim],
    *,
    domain: str = "general",
    layers_enabled: dict[str, bool] | None = None,
) -> Decision:
    risk, factors = classify_risk(report, claims, domain=domain)

    rule_id, note = "R-DEFAULT", "no rule matched; defaulting to human review"
    outcome = Outcome.REVIEW
    for candidate_id, predicate, candidate_outcome, candidate_note in _RULES:
        if predicate(report, risk, claims):
            rule_id, outcome, note = candidate_id, candidate_outcome, candidate_note
            break

    disabled = sorted(k for k, v in (layers_enabled or {}).items() if not v)
    if disabled:
        factors.append(f"validators switched off for this run: {', '.join(disabled)}")

    return Decision(
        outcome=outcome,
        risk=risk,
        rule_id=rule_id,
        triggering_factors=[note] + factors,
        inputs={
            "band": report.band.value,
            "score": report.score,
            "ledger": report.ledger.model_dump(),
            "expressed_confidence": report.expressed_confidence.value,
            "supported_confidence": report.supported_confidence.value,
            "false_certainty": report.false_certainty,
            "evidence_strength": report.evidence_strength,
            "source_quality": report.source_quality,
            "recency": report.recency,
            "domain": domain,
            "domain_multiplier": DOMAIN_SENSITIVITY.get(domain, 1.0),
            "has_hard_basis": _has_hard_basis(claims),
            "judge_only_condemnation": _judge_only_condemnation(claims),
            "layers_enabled": dict(sorted((layers_enabled or {}).items())),
        },
        table_version=DECISION_TABLE_VERSION,
    )


assert Confidence  # part of the documented input surface
