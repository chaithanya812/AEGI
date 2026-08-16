"""MP-13 — Reliability Scoring Engine.

The primary output is the **ledger**: how many claims were verified, uncertain, unsupported,
contradicted. Not a percentage. MP-13 is blunt about why — "87% reliable" is meaningless and
quietly trains everyone to ignore it. Four verified and one contradicted is actionable;
"82%" is wallpaper.

A single number is still computed, because a client's eye goes to one, and a band
(VERIFIED / QUALIFIED / UNRELIABLE) sits above both. But the number is deliberately
subordinate in the contract and in the UI, and it is derived from the ledger rather than the
other way round.

**Non-checkable claims are excluded from the denominator.** An output that is entirely
opinion is not 0% reliable; there was simply nothing to check, and the band says so.
"""

from __future__ import annotations

from ..contracts import Band, Claim, Confidence, Ledger, ReliabilityReport, Support
from . import certainty

#: How much credit each verdict earns. UNKNOWN sits mid-scale on purpose: unverified is
#: not the same as wrong, and scoring it as wrong would punish honesty about coverage.
_WEIGHTS: dict[Support, float] = {
    Support.SUPPORTED: 1.0,
    Support.PARTIALLY_SUPPORTED: 0.6,
    Support.UNKNOWN: 0.5,
    Support.UNSUPPORTED: 0.15,
    Support.CONTRADICTED: 0.0,
}


def build_ledger(claims: list[Claim]) -> Ledger:
    ledger = Ledger()
    for claim in claims:
        if claim.status is Support.SUPPORTED:
            ledger.supported += 1
        elif claim.status is Support.PARTIALLY_SUPPORTED:
            ledger.partially_supported += 1
        elif claim.status is Support.UNSUPPORTED:
            ledger.unsupported += 1
        elif claim.status is Support.CONTRADICTED:
            ledger.contradicted += 1
        elif claim.status is Support.UNKNOWN:
            ledger.unknown += 1
        else:
            ledger.not_applicable += 1
    return ledger


def _band(ledger: Ledger) -> Band:
    total = ledger.checkable_total
    if total == 0:
        return Band.QUALIFIED  # nothing checkable — neither clean nor caught
    if ledger.contradicted:
        return Band.UNRELIABLE
    if ledger.unsupported:
        return (
            Band.UNRELIABLE if ledger.unsupported / total > 0.34 else Band.QUALIFIED
        )
    if ledger.unknown or ledger.partially_supported:
        return Band.QUALIFIED
    return Band.VERIFIED


def _dimensions(claims: list[Claim]) -> tuple[float, float, float]:
    """Evidence strength, source quality and recency, averaged over claims that had
    evidence at all. Reported separately because they fail independently: strong sources
    can be stale, and fresh sources can be weak."""
    with_evidence = [c for c in claims if c.evidence]
    if not with_evidence:
        return 0.0, 0.0, 0.0

    strength = sum(
        max((e.relevance for e in c.evidence), default=0.0) for c in with_evidence
    ) / len(with_evidence)
    quality = sum(
        max((e.authority for e in c.evidence), default=0.0) for c in with_evidence
    ) / len(with_evidence)

    ages = [
        min((e.recency_days for e in c.evidence if e.recency_days is not None), default=None)
        for c in with_evidence
    ]
    ages = [a for a in ages if a is not None]
    if ages:
        avg_age = sum(ages) / len(ages)
        recency = max(0.0, min(1.0, 1.0 - avg_age / 1825))  # five years to zero
    else:
        recency = 0.0

    return round(strength, 3), round(quality, 3), round(recency, 3)


def score_for(ledger: Ledger, claims: list[Claim]) -> int:
    total = ledger.checkable_total
    if total == 0:
        return 50  # nothing to check; not a failure and not a pass

    checkable = [c for c in claims if c.checkable]
    earned = sum(_WEIGHTS.get(c.status, 0.0) for c in checkable)
    base = earned / total

    # A single contradicted claim should dominate the headline, because a reader who acts
    # on it is wrong regardless of how many neighbouring sentences were fine.
    if ledger.contradicted:
        base = min(base, 0.20 / max(1, ledger.contradicted))

    return int(round(max(0.0, min(1.0, base)) * 100))


def assess(text: str, claims: list[Claim]) -> ReliabilityReport:
    ledger = build_ledger(claims)
    strength, quality, recency = _dimensions(claims)
    expressed, supported, false_certainty, note = certainty.assess(text, claims)

    band = _band(ledger)
    score = score_for(ledger, claims)

    # False certainty cannot leave an output looking clean. A flatly-stated answer whose
    # evidence does not hold up is the exact failure the lab exists to surface.
    if false_certainty and band is Band.VERIFIED:
        band = Band.QUALIFIED

    return ReliabilityReport(
        ledger=ledger,
        band=band,
        score=score,
        evidence_strength=strength,
        source_quality=quality,
        recency=recency,
        expressed_confidence=expressed,
        supported_confidence=supported,
        false_certainty=false_certainty,
        certainty_note=note,
    )


assert Confidence  # re-exported for callers reading the contract
