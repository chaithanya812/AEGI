"""MP-16 — Safe Response Engine.

What the human actually reads when something is caught. **Never a bare error.**

"I can't confirm that — the note saying warfarin is from March, and the medication list was
updated in November" is useful. "Request blocked (code 4012)" teaches people to route around
the system, which is worse than not having it at all.

**Deliberate deviation from MP-16:** the PRD specifies a templated explanation plus an LLM
pass for fluency, followed by a deterministic check that the template's facts survived that
pass. v1 ships the template only. The fluency pass is the one place in this pipeline where a
model would be rewriting the exact sentence that tells a user the model got something wrong,
and the guard for it is non-trivial to build properly. Until that guard exists, a slightly
stiff sentence that is definitely accurate beats a fluent one that might not be. This is a
v2 item, not an oversight.
"""

from __future__ import annotations

from ..contracts import Claim, Decision, Outcome, ReliabilityReport, Support

_ORDER = {
    Support.CONTRADICTED: 0,
    Support.UNSUPPORTED: 1,
    Support.PARTIALLY_SUPPORTED: 2,
    Support.UNKNOWN: 3,
}


def _worst_claims(claims: list[Claim], limit: int = 3) -> list[Claim]:
    flagged = [c for c in claims if c.status in _ORDER]
    flagged.sort(key=lambda c: (_ORDER[c.status], -len(c.text)))
    return flagged[:limit]


def _cite(claim: Claim) -> str:
    if not claim.evidence:
        return ""
    item = claim.evidence[0]
    return f" (source: {item.doc_title}, {item.section}, page {item.page})"


def compose(
    *, report: ReliabilityReport, decision: Decision, claims: list[Claim], output_text: str
) -> str | None:
    """Returns the message to show in place of, or alongside, the output.

    ``None`` for a clean ALLOW — there is nothing to say, and saying something anyway
    devalues the times there is.
    """
    if decision.outcome is Outcome.ALLOW:
        return None

    worst = _worst_claims(claims)
    lines: list[str] = []

    if decision.outcome in (Outcome.BLOCK, Outcome.REFUSE):
        lines.append("This output was withheld because it states things the evidence does not support.")
    elif decision.outcome is Outcome.REVIEW:
        lines.append("This output needs a person to look at it before it is relied on.")
    else:
        lines.append("This output can be used, but parts of it did not hold up against the evidence.")

    for claim in worst:
        if claim.status is Support.CONTRADICTED:
            verb = "is contradicted by the source"
        elif claim.status is Support.UNSUPPORTED:
            verb = "is not supported by anything found"
        elif claim.status is Support.PARTIALLY_SUPPORTED:
            verb = "is only partly supported"
        else:
            verb = "could not be checked either way"

        reason = claim.reasoning.strip()
        if reason and not reason.endswith("."):
            reason += "."
        lines.append(f'· "{claim.text}" — {verb}. {reason}{_cite(claim)}')

    if report.false_certainty:
        lines.append(
            f"It was also stated far more confidently than the evidence allows: "
            f"expressed {report.expressed_confidence.value}, supported "
            f"{report.supported_confidence.value}."
        )

    ledger = report.ledger
    if ledger.checkable_total:
        lines.append(
            f"Ledger: {ledger.supported} verified, {ledger.partially_supported} partial, "
            f"{ledger.unknown} unknown, {ledger.unsupported} unsupported, "
            f"{ledger.contradicted} contradicted"
            + (f", {ledger.not_applicable} not checkable" if ledger.not_applicable else "")
            + f". Decision {decision.outcome.value} under rule {decision.rule_id}."
        )

    if decision.rule_id == "R-JUDGE-ONLY":
        lines.append(
            "Note: the only thing against this output is the judge model's assessment, with no "
            "deterministic check confirming it. That is not enough to block on, so it is being "
            "escalated rather than rejected."
        )

    return "\n".join(lines)
