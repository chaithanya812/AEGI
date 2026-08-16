"""MP-11 — Citation Validator.

Two distinct failures, and they need different machinery:

1. **Unresolvable citation.** The reference does not exist in the corpus at all. Pure
   lookup, no judgement, no model. This is the fabricated-citation case.

2. **Citation mismatch.** The reference exists and is correctly formatted and points at a
   source that says something *different* from the sentence it was attached to.

The second is the trust-corrosive one, and MP-11 names why it survives human review: the
presence of a citation is exactly what stops people checking it. So where the claim and the
cited source both carry figures, the comparison is arithmetic rather than opinion.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

from ..contracts import CheckOutcome, CheckResult, EvidenceItem
from ..corpus import load_documents
from .quantities import compare_quantities

#: Corpus document identifiers look like REF-EIFFEL-01 / MAT-NW-BOARD-FY2025.
_DOC_ID_RE = re.compile(r"\b([A-Z]{3,4}(?:-[A-Z0-9]{2,10}){1,3})\b")
_CLAUSE_RE = re.compile(r"\bclause\s+(\d+(?:\.\d+)*)\b", re.IGNORECASE)
_PAGE_RE = re.compile(r"\bp(?:age|\.)?\s*(\d{1,4})\b", re.IGNORECASE)


@dataclass
class CitationRef:
    kind: str  # doc_id | clause | page
    value: str
    raw: str


@lru_cache(maxsize=1)
def _known_doc_ids() -> frozenset[str]:
    return frozenset(doc.doc_id for doc in load_documents())


@lru_cache(maxsize=1)
def _known_clauses() -> frozenset[str]:
    """Clause numbers that actually appear in a corpus document heading or body."""
    from ..corpus import build_chunks

    found: set[str] = set()
    for chunk in build_chunks():
        for match in re.finditer(r"\b(\d+\.\d+)\b", chunk.text):
            found.add(match.group(1))
        for match in _CLAUSE_RE.finditer(chunk.section + " " + chunk.text):
            found.add(match.group(1))
    return frozenset(found)


def extract_citations(text: str) -> list[CitationRef]:
    refs: list[CitationRef] = []
    seen: set[tuple[str, str]] = set()
    for match in _DOC_ID_RE.finditer(text):
        key = ("doc_id", match.group(1))
        if key not in seen:
            seen.add(key)
            refs.append(CitationRef("doc_id", match.group(1), match.group(0)))
    for match in _CLAUSE_RE.finditer(text):
        key = ("clause", match.group(1))
        if key not in seen:
            seen.add(key)
            refs.append(CitationRef("clause", match.group(1), match.group(0)))
    return refs


def validate(
    claim_text: str, evidence: list[EvidenceItem]
) -> tuple[list[CheckResult], str | None]:
    """Returns (checks, decisive_failure_detail).

    A decisive failure means the claim is CONTRADICTED on deterministic grounds and the
    judge is not consulted — there is nothing for it to add once the arithmetic disagrees.
    """
    checks: list[CheckResult] = []
    decisive: str | None = None

    # --- 1. resolvability ---------------------------------------------------
    refs = extract_citations(claim_text)
    for ref in refs:
        if ref.kind == "doc_id":
            known = ref.value in _known_doc_ids()
            checks.append(
                CheckResult(
                    name="citation.resolve",
                    module="MP-11",
                    outcome=CheckOutcome.PASS if known else CheckOutcome.FAIL,
                    detail=(
                        f"cited document {ref.value} exists in the corpus"
                        if known
                        else f"cited document {ref.value} does not exist in the corpus — "
                        f"the citation is correctly formatted and refers to nothing"
                    ),
                    deterministic=True,
                )
            )
            if not known and decisive is None:
                decisive = (
                    f"the citation {ref.value} cannot be resolved: no such document exists. "
                    f"A well-formatted reference to a non-existent source is a fabricated citation."
                )
        elif ref.kind == "clause":
            known = ref.value in _known_clauses()
            checks.append(
                CheckResult(
                    name="citation.resolve",
                    module="MP-11",
                    outcome=CheckOutcome.PASS if known else CheckOutcome.INCONCLUSIVE,
                    detail=(
                        f"clause {ref.value} appears in the corpus"
                        if known
                        else f"clause {ref.value} does not appear in any indexed document"
                    ),
                    deterministic=True,
                )
            )

    # --- 2. does any retrieved source actually support the figure? ----------
    # Every evidence item is checked, not just the top-ranked one. Retrieval ranks by
    # relevance to the whole proposition, so the passage carrying the decisive *number* is
    # frequently second or third — and checking only the first hit silently loses the
    # deterministic catch, pushing the claim onto the judge for no reason.
    if evidence:
        supporting: tuple[EvidenceItem, object] | None = None
        disagreements: list[tuple[EvidenceItem, object]] = []
        any_comparable = False
        claim_qs_all: list = []

        for item in evidence:
            comparisons, claim_qs = compare_quantities(claim_text, item.quote)
            claim_qs_all = claim_qs or claim_qs_all
            for comparison in comparisons:
                any_comparable = True
                if comparison.satisfied:
                    if supporting is None:
                        supporting = (item, comparison)
                elif comparison.severity in ("MODERATE", "SEVERE"):
                    disagreements.append((item, comparison))

        if claim_qs_all and not any_comparable:
            checks.append(
                CheckResult(
                    name="citation.figure",
                    module="MP-11",
                    outcome=CheckOutcome.INCONCLUSIVE,
                    detail=(
                        f"the claim states a figure ({claim_qs_all[0].display}) that no "
                        f"retrieved source addresses as the same measure"
                    ),
                    deterministic=True,
                )
            )

        if supporting is not None:
            item, comparison = supporting
            checks.append(
                CheckResult(
                    name="citation.figure",
                    module="MP-11",
                    outcome=CheckOutcome.PASS,
                    detail=(
                        f"{comparison.detail} — {item.doc_id} {item.section}, page {item.page}"
                    ),
                    deterministic=True,
                )
            )
        elif disagreements:
            # Highest-authority disagreement governs; a wiki page should not be the one
            # quoted back to the user when an audited account is also in the set.
            item, comparison = max(disagreements, key=lambda pair: pair[0].authority)
            for other_item, other in disagreements:
                checks.append(
                    CheckResult(
                        name="citation.figure",
                        module="MP-11",
                        outcome=CheckOutcome.FAIL,
                        detail=(
                            f"{other.detail} "
                            f"({other.severity.lower()}, {other.diff * 100:.1f}% apart) "
                            f"— {other_item.doc_id} {other_item.section}, page {other_item.page}"
                        ),
                        deterministic=True,
                    )
                )
            if decisive is None:
                decisive = (
                    f"{comparison.detail}. The source is {item.doc_title} "
                    f"({item.doc_id}, {item.section}, page {item.page}). "
                    f"The figures differ by {comparison.diff * 100:.1f}%."
                )

    if not checks:
        checks.append(
            CheckResult(
                name="citation",
                module="MP-11",
                outcome=CheckOutcome.SKIP,
                detail="no citation or figure in this claim to resolve",
                deterministic=True,
            )
        )

    return checks, decisive
