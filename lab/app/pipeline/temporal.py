"""MP-12 — Temporal Validation Engine.

Three checks, all arithmetic against a reference clock:

1. **Future event described as concluded.** "Who won the 2027 World Cup" cannot have a
   winner because 2027 has not happened. This is the check that makes the hallucination
   demo deterministic: it fires on date comparison regardless of what the model produced,
   so the outcome does not depend on the model cooperating.

2. **Superseded evidence.** A claim sourced from a document that a later document replaced
   is not false — it is *stale*, and stale is the dangerous case precisely because the text
   is accurate and every other validator passes it.

3. **Stale evidence by age.** Old but not formally superseded, which is a warning rather
   than a failure.

None of this involves a model. That is the point.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from ..contracts import CheckOutcome, CheckResult, EvidenceItem
from ..corpus import supersession_map

_YEAR_RE = re.compile(r"\b(1[5-9]\d{2}|20\d{2}|21\d{2})\b")

#: Verbs and constructions that assert something already happened. A future-dated year
#: alongside one of these is the contradiction; a future-dated year with "will" is not.
_CONCLUDED_RE = re.compile(
    r"\b("
    r"won|win[s]?\b|winner|awarded|received|completed|concluded|finished|ended|"
    r"launched|released|published|signed|elected|appointed|died|founded|built|"
    r"beat|beats|defeated|defeats|clinched|lifted|triumphed|crowned|"
    r"was|were|has been|have been|had been|became|took place|occurred|happened"
    r")\b",
    re.IGNORECASE,
)
# Note: "held" and "hosted" are deliberately absent. Both appear in perfectly correct
# forward-looking phrasing ("is scheduled to be held in Brazil"), and including them made a
# true statement about a scheduled tournament read as an assertion that it had finished.

_FUTURE_INTENT_RE = re.compile(
    r"\b(will|shall|is scheduled|are scheduled|is due|expected to|projected|forecast|"
    r"planned|upcoming|to be held)\b",
    re.IGNORECASE,
)

#: Statements that a future event has *not* happened. These must never trip the
#: future-event check, and getting this wrong is worse than missing a hallucination.
#:
#: The bug this exists to prevent, found in production: asked who won the 2027 World Cup, the
#: model correctly answered "it has not taken place yet, there is no winner to report" — and
#: the checker matched the word "winner" beside the year 2027 and declared the claim
#: contradicted. A validator that punishes a model for being appropriately careful is worse
#: than no validator, because it trains people to switch it off.
_NON_OCCURRENCE_RE = re.compile(
    r"("
    r"\bno (?:winner|winners|outcome|result|results|score|champion|recipient|laureate)\b"
    r"|\bthere (?:is|are|was|were) no\b"
    r"|\b(?:has|have|had|is|are|was|were|does|do|did|can|could|cannot|will) ?n[o']?t\b"
    r"|\bnot (?:yet|taken place|been held|been awarded|occurred|happened|concluded|completed"
    r"|finished|played|decided|announced|exist|available)\b"
    r"|\byet to (?:be|take place|happen|occur|conclude)\b"
    r"|\bno such\b|\bdoes not exist\b|\bdo not exist\b|\bnever (?:took place|happened|held)\b"
    r"|\bhas not\b|\bhaven't\b|\bhasn't\b|\bcan't\b|\bwon't\b|\bisn't\b|\baren't\b"
    # Determiner negation with a trailing "yet": "No Nobel Prize has been awarded for 2028
    # yet." The negation is carried by "No", not by a negated verb.
    r"|^\s*no\s+\w"
    r"|\bnone (?:has|have|was|were)\b"
    # "yet" only counts as non-occurrence when a negator is nearby, so the adversative sense
    # ("Argentina won, yet Brazil dominated") does not wrongly excuse a fabricated result.
    r"|\b(?:not|no|none|never)\b[^.]{0,40}\byet\b"
    r")",
    re.IGNORECASE,
)

_STALE_AFTER_DAYS = 900


@dataclass
class TemporalFinding:
    outcome: CheckOutcome
    detail: str
    contradicted: bool = False
    superseding_doc: str | None = None


def reference_clock(configured: str | None = None) -> date:
    if configured:
        try:
            return date.fromisoformat(configured)
        except ValueError:
            pass
    return date.today()


def years_in(text: str) -> list[int]:
    return [int(m.group(1)) for m in _YEAR_RE.finditer(text)]


def check_future_event(claim_text: str, today: date) -> TemporalFinding | None:
    """Fires only when a year strictly after the current year is asserted as concluded."""
    future_years = [y for y in years_in(claim_text) if y > today.year]
    if not future_years:
        return None

    # Checked before anything else: a claim that the event has *not* happened is consistent
    # with the date, not in conflict with it, however many outcome words it contains.
    if _NON_OCCURRENCE_RE.search(claim_text):
        return TemporalFinding(
            outcome=CheckOutcome.PASS,
            detail=(
                f"references {future_years[0]}, which is in the future, and correctly states "
                f"that the event has not happened rather than asserting an outcome"
            ),
        )

    if _FUTURE_INTENT_RE.search(claim_text) and not _CONCLUDED_RE.search(claim_text):
        return TemporalFinding(
            outcome=CheckOutcome.PASS,
            detail=(
                f"references {future_years[0]}, which is in the future, but states it as "
                f"scheduled or expected rather than as completed"
            ),
        )

    if not _CONCLUDED_RE.search(claim_text):
        return TemporalFinding(
            outcome=CheckOutcome.INCONCLUSIVE,
            detail=f"references the future year {future_years[0]} without asserting completion",
        )

    year = future_years[0]
    return TemporalFinding(
        outcome=CheckOutcome.FAIL,
        contradicted=True,
        detail=(
            f"the claim describes {year} as something that has already happened, but "
            f"{year} is in the future relative to the reference clock of "
            f"{today.isoformat()}. No outcome can exist for an event that has not occurred."
        ),
    )


def check_supersession(evidence: list[EvidenceItem]) -> TemporalFinding | None:
    replaced_by = supersession_map()
    for item in evidence:
        newer = replaced_by.get(item.doc_id)
        if newer:
            return TemporalFinding(
                outcome=CheckOutcome.FAIL,
                detail=(
                    f"the supporting evidence comes from {item.doc_id}, which has been "
                    f"superseded by {newer}. The text may read as accurate while stating a "
                    f"position that no longer applies."
                ),
                superseding_doc=newer,
            )
    return None


def check_staleness(evidence: list[EvidenceItem]) -> TemporalFinding | None:
    ages = [e.recency_days for e in evidence if e.recency_days is not None]
    if not ages:
        return None
    youngest = min(ages)
    if youngest > _STALE_AFTER_DAYS:
        return TemporalFinding(
            outcome=CheckOutcome.INCONCLUSIVE,
            detail=(
                f"the freshest supporting document is {youngest} days old; the claim may be "
                f"accurate as written and still out of date"
            ),
        )
    return None


def validate(
    claim_text: str, evidence: list[EvidenceItem], *, today: date
) -> tuple[list[CheckResult], TemporalFinding | None]:
    """Returns the check trail plus the single finding that should drive the verdict,
    if any. Future-event failures outrank supersession, which outranks staleness."""
    checks: list[CheckResult] = []
    decisive: TemporalFinding | None = None

    future = check_future_event(claim_text, today)
    if future:
        checks.append(
            CheckResult(
                name="temporal.future_event",
                module="MP-12",
                outcome=future.outcome,
                detail=future.detail,
                deterministic=True,
            )
        )
        if future.outcome is CheckOutcome.FAIL:
            decisive = future

    if decisive is None:
        superseded = check_supersession(evidence)
        if superseded:
            checks.append(
                CheckResult(
                    name="temporal.supersession",
                    module="MP-12",
                    outcome=superseded.outcome,
                    detail=superseded.detail,
                    deterministic=True,
                )
            )
            decisive = superseded

    if decisive is None:
        stale = check_staleness(evidence)
        if stale:
            checks.append(
                CheckResult(
                    name="temporal.staleness",
                    module="MP-12",
                    outcome=stale.outcome,
                    detail=stale.detail,
                    deterministic=True,
                )
            )

    if not checks:
        checks.append(
            CheckResult(
                name="temporal",
                module="MP-12",
                outcome=CheckOutcome.PASS,
                detail="no temporal inconsistency found",
                deterministic=True,
            )
        )

    return checks, decisive
