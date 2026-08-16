"""MP-10 — Contradiction Engine.

Finds conflicts *between sources*, independently of any claim. If the audited accounts say
GBP 2.8bn and the press release says GBP 2.9bn, that is a finding in its own right —
arguably more valuable to the customer than the answer they asked for, because nobody was
looking for it.

Numbers and dates are normalised before comparison (see quantities.py), so "5 mg", "5mg"
and "0.005 g" do not register as a disagreement. Severity is graded rather than binary:
rounding is not an alarm, a doubled figure is not a footnote.

Where two sources disagree, authority decides which one governs — an audited account
outranks a preliminary statement from the same company, and the engine says so rather than
leaving the reader to guess.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..contracts import EvidenceItem
from ..corpus import supersession_map
from .quantities import (
    Quantity,
    extract_quantities,
    relative_difference,
    severity_for,
    shares_measure,
)


@dataclass
class Contradiction:
    left_doc: str
    right_doc: str
    left_section: str
    right_section: str
    dimension: str
    left_value: str
    right_value: str
    severity: str
    diff: float
    governing_doc: str
    detail: str


@dataclass
class ContradictionReport:
    pairs: list[Contradiction] = field(default_factory=list)

    @property
    def worst(self) -> str:
        order = {"MINOR": 1, "MODERATE": 2, "SEVERE": 3}
        return max((p.severity for p in self.pairs), key=lambda s: order.get(s, 0), default="NONE")

    def to_dicts(self) -> list[dict]:
        return [p.__dict__ for p in self.pairs]


#: Cross-source contradiction needs a much higher bar than claim-vs-evidence comparison,
#: because there is no claim to anchor it: any two numbers in a corpus can be subtracted, and
#: most such subtractions are meaningless. So both figures must be *labelled with the same
#: measure* by one of these words.
#:
#: Everything this excludes was a real false positive during development — a squad size
#: against a clause number, a tower in Paris against a tower in Dubai, this year's bookings
#: against last year's revenue. Each was reported as SEVERE with a confident percentage, which
#: is worse than saying nothing: a client who spots one nonsense finding stops believing the
#: real ones on the same screen.
_MEASURE_NOUNS = frozenset(
    """revenue revenues bookings turnover sales profit loss margin ebitda earnings
    cap capped liability liabilities indemnity indemnities damages penalty fee fees
    charges price cost costs salary compensation valuation funding
    headcount employees staff population
    height tall altitude depth length distance width
    dose dosage concentration weight mass volume
    retention period term duration years months days
    growth share rate ratio percentage yield""".split()
)


def _comparable(a: Quantity, b: Quantity) -> bool:
    if a.dimension != b.dimension:
        return False
    if a.dimension == "year":
        return False  # dates are MP-12's job, not a numeric spread
    if a.dimension == "currency" and a.currency and b.currency and a.currency != b.currency:
        return False
    # An inequality is not in conflict with a point value that satisfies it.
    if a.comparator != "=" or b.comparator != "=":
        return False
    if not shares_measure(a, b):
        return False
    # Strictest gate: the shared context must name a measure, not merely a company or a unit.
    return bool(a.context & b.context & _MEASURE_NOUNS)


def _same_matter(left: EvidenceItem, right: EvidenceItem) -> bool:
    """Only compare documents from the same customer matter.

    A genuine cross-source conflict is a conflict inside one body of work — an agreement
    against its own amendment, audited accounts against the company's own press release.
    Two unrelated reference articles disagreeing about two different towers is arithmetic,
    not a finding.
    """
    return bool(left.matter) and left.matter == right.matter


def _governing(left: EvidenceItem, right: EvidenceItem) -> tuple[str, str]:
    """Which document wins, and why.

    Supersession outranks authority tier. An amendment and the agreement it amends usually
    sit in the *same* tier, so comparing authority alone would let the stale figure govern —
    which is precisely the failure MP-12 exists to catch.
    """
    replaced_by = supersession_map()
    if replaced_by.get(left.doc_id) == right.doc_id:
        return right.doc_id, f"{right.doc_id} supersedes {left.doc_id} and governs"
    if replaced_by.get(right.doc_id) == left.doc_id:
        return left.doc_id, f"{left.doc_id} supersedes {right.doc_id} and governs"
    if left.authority > right.authority:
        return left.doc_id, f"{left.doc_id} carries the higher authority tier and governs"
    if right.authority > left.authority:
        return right.doc_id, f"{right.doc_id} carries the higher authority tier and governs"
    return "", "both sources carry equal authority; neither governs on its own"


def detect(evidence_groups: list[list[EvidenceItem]]) -> ContradictionReport:
    """Compares sources **within each claim's evidence set**, not across the whole run.

    Pooling every passage retrieved for a multi-topic paragraph and comparing everything to
    everything is how you get a squad size "contradicting" a tower's height. The honest
    question is narrower: for this one proposition, do my sources disagree with each other?
    """
    report = ContradictionReport()
    seen: set[tuple[str, ...]] = set()
    order = {"MINOR": 1, "MODERATE": 2, "SEVERE": 3}

    for group in evidence_groups:
        if len(group) < 2:
            continue

        quantities: list[tuple[EvidenceItem, Quantity]] = []
        for item in group:
            for qty in extract_quantities(item.quote):
                quantities.append((item, qty))

        for i, (left_item, left_qty) in enumerate(quantities):
            for right_item, right_qty in quantities[i + 1 :]:
                if left_item.doc_id == right_item.doc_id:
                    continue  # a document restating its own figure is not a contradiction
                if not _same_matter(left_item, right_item):
                    continue
                if not _comparable(left_qty, right_qty):
                    continue

                diff = relative_difference(left_qty.value, right_qty.value)
                severity = severity_for(diff)
                if severity == "MATCH":
                    continue

                # Values are sorted into the key as well as document IDs, so the same pair
                # found from either direction collapses into one finding rather than two
                # mirror-image rows.
                key = tuple(
                    sorted([left_item.doc_id, right_item.doc_id])
                    + [left_qty.dimension]
                    + sorted([left_qty.display, right_qty.display])
                )
                if key in seen:
                    continue
                seen.add(key)

                governing, why = _governing(left_item, right_item)
                report.pairs.append(
                    Contradiction(
                        left_doc=left_item.doc_id,
                        right_doc=right_item.doc_id,
                        left_section=left_item.section,
                        right_section=right_item.section,
                        dimension=left_qty.dimension,
                        left_value=left_qty.display,
                        right_value=right_qty.display,
                        severity=severity,
                        diff=round(diff, 6),
                        governing_doc=governing,
                        detail=(
                            f"{left_item.doc_id} states {left_qty.display} while "
                            f"{right_item.doc_id} states {right_qty.display} "
                            f"({severity.lower()}, {diff * 100:.1f}% apart). {why}."
                        ),
                    )
                )

    report.pairs.sort(key=lambda p: order.get(p.severity, 0), reverse=True)
    return report
