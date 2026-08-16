"""Regression tests for the deterministic layer. No model, no network, no API key.

These cover the checks that carry the product's credibility, so they must stay fast enough to
run on every change. Two of the groups exist because of bugs found in production rather than
in theory, and the comments say which — those are the ones not to "tidy away".

    python scripts/test_deterministic.py
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.pipeline.claims import classify, split_sentences  # noqa: E402
from app.pipeline.quantities import (  # noqa: E402
    compare_quantities,
    extract_quantities,
    shares_measure,
)
from app.pipeline.temporal import check_future_event  # noqa: E402

CLOCK = date(2026, 8, 16)
failures: list[str] = []


def check(label: str, got: object, want: object) -> None:
    if got != want:
        failures.append(f"{label}: got {got!r}, wanted {want!r}")
        print(f"  BAD  {label}\n         got  {got!r}\n         want {want!r}")
    else:
        print(f"  ok   {label}")


# --- MP-12 future events ------------------------------------------------------
# The PASS cases are the important half. Found in production: asked who won the 2027 World
# Cup, the model answered correctly that it had not happened and there was no winner — and
# the checker matched "winner" beside "2027" and called it contradicted. Punishing a model
# for being careful is worse than missing a hallucination, because people switch it off.
print("\nMP-12 future events — must NOT flag correct caution")
for text, want in [
    ("The 2027 FIFA Women's World Cup has not taken place yet.", "PASS"),
    ("There is no winner or final score to report for the 2027 World Cup.", "PASS"),
    ("The 2027 Women's World Cup is scheduled to be held in Brazil.", "PASS"),
    ("No Nobel Prize has been awarded for 2028 yet.", "PASS"),
    ("The 2030 World Cup will be held in Morocco, Spain and Portugal.", "PASS"),
    ("None has been awarded for the 2029 prize.", "PASS"),
]:
    finding = check_future_event(text, CLOCK)
    check(text[:58], finding.outcome.value if finding else "NONE", want)

print("\nMP-12 future events — must flag fabricated outcomes")
for text, want in [
    ("Argentina won the 2027 FIFA World Cup.", "FAIL"),
    ("Argentina beat Brazil 3-1 in the 2027 World Cup final.", "FAIL"),
    ("Dr XYZ received the 2028 Nobel Prize in Quantum Computing.", "FAIL"),
    ("The 2029 merger was completed in March.", "FAIL"),
    # Adversative "yet" must not launder a fabrication into a non-occurrence claim.
    ("Argentina won the 2027 World Cup, yet Brazil dominated possession.", "FAIL"),
]:
    finding = check_future_event(text, CLOCK)
    check(text[:58], finding.outcome.value if finding else "NONE", want)


# --- quantities ---------------------------------------------------------------
print("\nQuantity extraction — identifiers are not measurements")
check(
    "clause 14.3 is a locator, not a number",
    [q.display for q in extract_quantities("The cap is set out in clause 14.3 of the MSA.")],
    [],
)
check(
    "document id fragments are skipped",
    [q.display for q in extract_quantities("See REF-TALLEST-01 and MAT-NW-XYZ-9999.")],
    [],
)
check(
    "bare years belong to MP-12",
    [q.display for q in extract_quantities("The tower was completed in 1889.")],
    [],
)
check(
    "currency with scale normalises",
    [(q.display, q.value) for q in extract_quantities("Revenue was GBP 2.8 billion.")],
    [("GBP 2.8 billion", 2.8e9)],
)
check(
    "comparator is captured",
    [(q.comparator, q.value) for q in extract_quantities("It stands at over 500 meters.")],
    [(">", 500.0)],
)
check(
    "mass units normalise to grams",
    [q.value for q in extract_quantities("The dose is 5mg.")]
    == [q.value for q in extract_quantities("The dose is 0.005 g.")],
    True,
)

print("\nSame dimension is not the same measure")
eiffel = extract_quantities("the Eiffel Tower stood 300 metres tall")[0]
burj = extract_quantities("the Burj Khalifa in Dubai reaches 828 metres")[0]
check("Paris height vs Dubai height not comparable", shares_measure(eiffel, burj), False)
revenue = extract_quantities("Revenue was GBP 2.8 billion")[0]
bookings = extract_quantities("total bookings of GBP 2.9 billion")[0]
check("revenue vs bookings not comparable", shares_measure(revenue, bookings), False)
rev_a = extract_quantities("Revenue was GBP 2.8 billion")[0]
rev_b = extract_quantities("reported revenue of GBP 4.2 billion")[0]
check("revenue vs revenue comparable", shares_measure(rev_a, rev_b), True)

print("\nMP-11 figure agreement")
comparisons, _ = compare_quantities(
    "Northwind reported FY2025 revenue of GBP 4.2 billion.",
    "Revenue for FY2025 was GBP 2.8 billion, representing growth of 33 percent.",
)
check("4.2bn vs 2.8bn is a severe mismatch", [c.severity for c in comparisons], ["SEVERE"])
check("and is not satisfied", [c.satisfied for c in comparisons], [False])

comparisons, _ = compare_quantities(
    "The tower is over 500 meters tall.",
    "At 330 metres the Eiffel Tower is not the tallest structure in Europe.",
)
check("'over 500m' vs 330m fails the comparator", [c.satisfied for c in comparisons], [False])


# --- MP-04/05 -----------------------------------------------------------------
print("\nSentence segmentation")
check(
    "decimals and clause numbers survive",
    len(split_sentences("Revenue was GBP 2.8 billion. See clause 14.3 for details.")),
    2,
)
check(
    "lowercase continuation still splits",
    len(split_sentences("It is over 500 meters. but i think burj kahalifa is taller")),
    2,
)
check(
    "spaced period splits",
    len(split_sentences("my name might be mark . tom and jerry is disny show")),
    2,
)
check("abbreviations do not split", len(split_sentences("Dr. Smith met Mr. Jones.")), 1)

print("\nMP-05 classification — unfalsifiable claims are never checkable")
for text, want_type, want_checkable in [
    ("my name might be mark", "UNVERIFIABLE", False),
    ("i think burj kahalifa is the tallest tower", "OPINION", False),
    ("You should review the contract first.", "RECOMMENDATION", False),
    ("Tom and Jerry is a Disney show.", "FACT", True),
    ("Revenue was GBP 2.8 billion.", "NUMERIC", True),
    ("The tower was completed in 1889.", "TEMPORAL", True),
]:
    claim_type, checkable, _hedged = classify(text)
    check(f"{text[:44]}", (claim_type.value, checkable), (want_type, want_checkable))

# --- MP-10 cross-source contradiction ----------------------------------------
# Runs the real pipeline with adapter=None, so retrieval and MP-10 are exercised against the
# actual corpus with no model and no network.
#
# The precision bar here is deliberately high. Cross-source contradiction has no claim to
# anchor it — any two numbers can be subtracted — and during development this produced a
# stream of confident nonsense: a squad size against a document-ID fragment, the Eiffel Tower
# against the Burj Khalifa, this year's bookings against last year's revenue. One nonsense
# finding costs the reader's belief in the real ones on the same screen, so noise is a
# correctness bug, not a cosmetic one.
print("\nMP-10 cross-source contradiction — precision matters more than recall")
import asyncio  # noqa: E402

from app.pipeline import run as run_mod  # noqa: E402


def contradictions_for(text: str) -> list[str]:
    result = asyncio.run(run_mod.verify_output(text, adapter=None, domain="legal"))
    return [f"{p['left_doc']}|{p['right_doc']}|{p['severity']}" for p in result.contradictions]


check(
    "finds the superseded indemnity cap",
    contradictions_for("The Northwind indemnity cap is GBP 2,000,000 and does not survive termination."),
    ["MAT-NW-AMD1-2024|MAT-NW-MSA-2023|SEVERE"],
)
check(
    "two different towers are not a contradiction",
    contradictions_for("The Eiffel Tower remains the tallest structure in Europe at over 500 meters."),
    [],
)
check(
    "bookings are not revenue",
    contradictions_for("Northwind Systems reported FY2025 revenue of GBP 4.2 billion."),
    [],
)
check(
    "a squad size conflicts with nothing",
    contradictions_for("The 2026 World Cup features 48 teams."),
    [],
)

print()
if failures:
    print(f"FAILED — {len(failures)} mismatch(es)")
    raise SystemExit(1)
print("all deterministic checks pass")
