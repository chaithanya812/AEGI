"""Quantity extraction and unit normalisation.

This module is small and boring and it is where a large share of the product's credibility
actually lives. When the lab says a cited source contradicts a claim about money or
distance, that verdict is arithmetic performed here — not a model's opinion — which is the
answer to "why should I trust your verifier?".

Normalisation happens *before* comparison, for the reason MP-10 gives: "5 mg", "5mg" and
"0.005 g" must not register as a disagreement, and "GBP 2.8 billion" must compare cleanly
against "2,800,000,000".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SCALES: dict[str, float] = {
    "hundred": 1e2,
    "thousand": 1e3,
    "k": 1e3,
    "lakh": 1e5,
    "million": 1e6,
    "m": 1e6,
    "mn": 1e6,
    "crore": 1e7,
    "billion": 1e9,
    "b": 1e9,
    "bn": 1e9,
    "trillion": 1e12,
    "tn": 1e12,
}

_CURRENCY_SYMBOLS = {"$": "USD", "£": "GBP", "€": "EUR", "₹": "INR", "¥": "JPY"}
_CURRENCY_CODES = {"usd", "gbp", "eur", "inr", "jpy", "chf", "cad", "aud", "sgd"}

#: Everything reduces to a base unit per dimension: metres, grams, seconds.
_UNITS: dict[str, tuple[str, float]] = {
    "mm": ("length", 0.001),
    "cm": ("length", 0.01),
    "m": ("length", 1.0),
    "metre": ("length", 1.0),
    "metres": ("length", 1.0),
    "meter": ("length", 1.0),
    "meters": ("length", 1.0),
    "km": ("length", 1000.0),
    "kilometre": ("length", 1000.0),
    "kilometres": ("length", 1000.0),
    "kilometer": ("length", 1000.0),
    "kilometers": ("length", 1000.0),
    "ft": ("length", 0.3048),
    "feet": ("length", 0.3048),
    "foot": ("length", 0.3048),
    "mile": ("length", 1609.344),
    "miles": ("length", 1609.344),
    "mcg": ("mass", 1e-6),
    "µg": ("mass", 1e-6),
    "mg": ("mass", 0.001),
    "g": ("mass", 1.0),
    "gram": ("mass", 1.0),
    "grams": ("mass", 1.0),
    "kg": ("mass", 1000.0),
    "kilogram": ("mass", 1000.0),
    "kilograms": ("mass", 1000.0),
    "tonne": ("mass", 1e6),
    "tonnes": ("mass", 1e6),
}

_COMPARATORS = {
    "over": ">",
    "above": ">",
    "more than": ">",
    "greater than": ">",
    "exceeding": ">",
    "exceeds": ">",
    "at least": ">=",
    "under": "<",
    "below": "<",
    "less than": "<",
    "fewer than": "<",
    "at most": "<=",
    "up to": "<=",
    "approximately": "~",
    "about": "~",
    "around": "~",
    "roughly": "~",
    "circa": "~",
    "nearly": "~",
}

_COMPARATOR_RE = re.compile(
    r"(?P<cmp>" + "|".join(sorted((re.escape(k) for k in _COMPARATORS), key=len, reverse=True)) + r")\s*$",
    re.IGNORECASE,
)

_QTY_RE = re.compile(
    r"""
    (?P<sym>[$£€₹¥])?\s*
    (?P<code>\b(?:USD|GBP|EUR|INR|JPY|CHF|CAD|AUD|SGD)\b)?\s*
    (?P<num>\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)
    # The single-letter scale forms need (?![A-Za-z]) or the alternation eats the "m" of
    # "5mg" as a scale and leaves "g" as the unit — parsing a 5 milligram dose as five
    # million grams, a factor of 10^9. Exactly the class of error this module exists to catch.
    \s*(?P<scale>hundred|thousand|lakh|million|crore|billion|trillion|bn|tn|mn|[kKmMbB](?![A-Za-z]))?
    \s*(?P<unit>%|percent|per\s?cent|mm|cm|km|kilometres|kilometers|kilometre|kilometer|metres|meters|metre|meter|miles|mile|feet|foot|ft|mcg|µg|mg|kg|kilograms|kilogram|grams|gram|tonnes|tonne|g|m)?
    \b
    """,
    re.IGNORECASE | re.VERBOSE,
)


@dataclass
class Quantity:
    raw: str
    value: float  # normalised into the base unit for its dimension
    dimension: str  # currency | length | mass | percent | count | year
    currency: str | None = None
    comparator: str = "="  # = | > | >= | < | <= | ~
    start: int = 0
    end: int = 0
    #: Words around the number, used to decide whether two figures measure the same thing.
    #: Without this, "48 teams" and "330 metres" are both just numbers and comparing them
    #: produces confident nonsense.
    context: frozenset[str] = frozenset()

    @property
    def display(self) -> str:
        return self.raw.strip()


#: Words that must never create a match between two figures. Three groups, all of which
#: caused real false positives before they were excluded:
#:   * ordinary function words;
#:   * the unit and scale words themselves — "metres" appears beside every height, so
#:     matching on it makes the Eiffel Tower contradict the Burj Khalifa;
#:   * locator nouns — "clause 14" and "clause 29" share the word "clause" and nothing else.
_CONTEXT_STOP = frozenset(
    """a an and are as at be by for from has have in is it its of on or that the to was
    were will with this these those there their them then than more less over under about
    around per total each which who whom whose while both same other than into
    metre metres meter meters kilometre kilometres kilometer kilometers mile miles feet
    foot gram grams kilogram kilograms tonne tonnes percent cent
    hundred thousand million billion trillion lakh crore
    clause section page paragraph article note item figure table exhibit schedule
    appendix step level tier version revision line row column part""".split()
)
_WORD_RE = re.compile(r"[A-Za-z][A-Za-z\-]{1,}")

#: A number directly after one of these is an identifier, not a measurement. "clause 14.3"
#: is a place to look something up; comparing it arithmetically against "clause 29" produces
#: a confident, severe, entirely meaningless contradiction.
_LOCATOR_WORDS = frozenset(
    """clause section page paragraph article note item figure fig table exhibit schedule
    appendix step level tier version rev no number line row column part chapter""".split()
)
_PRECEDING_WORD_RE = re.compile(r"([A-Za-z]+)[\s\.]*$")


#: Context must not cross a markdown table cell wall or a paragraph break.
#:
#: Table layout was manufacturing false matches: in a results table, `| GBP 2.1 billion |` sits
#: next to `| Gross margin |`, so last year's revenue picked up "margin" as its subject and
#: then "matched" this year's bookings. Physical adjacency in a table says nothing about
#: whether two figures measure the same thing.
#:
#: A *single* newline is not a boundary. Markdown soft-wraps prose mid-sentence, so treating
#: every newline as a wall cut "shall be capped at\nGBP 2,000,000" in half and lost the one
#: cross-source conflict in the corpus actually worth reporting. Cells are walled by `|`,
#: which already isolates table rows from each other since every row starts with one.
_CELL_BOUNDARY = re.compile(r"\||\n[ \t]*\n")


def _segment_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    left = max(0, start - 60)
    right = min(len(text), end + 60)
    before = text[left:start]
    after = text[end:right]

    matches = list(_CELL_BOUNDARY.finditer(before))
    if matches:
        left = start - (len(before) - matches[-1].end())

    match = _CELL_BOUNDARY.search(after)
    if match:
        right = end + match.start()

    return left, right


def _context_words(text: str, start: int, end: int) -> frozenset[str]:
    """Four words either side, lowercased, stopwords dropped, confined to one line or cell.

    "revenue of GBP 2.8 billion" -> {revenue}; "48 teams" -> {teams}. That is enough to tell a
    headcount from a height.

    Four rather than two, because the subject noun is often further away than it looks:
    "Revenue for FY2025 was GBP 2.8 billion" puts "Revenue" three tokens back, and a
    two-word window missed it — so a claim of GBP 4.2bn revenue failed to compare against
    the audited figure at all, and the deterministic catch was silently lost.
    """
    left, right = _segment_bounds(text, start, end)
    before = _WORD_RE.findall(text[left:start])[-4:]
    after = _WORD_RE.findall(text[end:right])[:4]
    words = {w.lower() for w in before + after}
    return frozenset(w for w in words if w not in _CONTEXT_STOP and len(w) >= 2)


def shares_measure(a: Quantity, b: Quantity) -> bool:
    """Do these two figures plausibly measure the same thing?

    Same dimension is not the same measure, and this was the single biggest source of
    nonsense findings during development. Two heights in metres are directly comparable as
    numbers and completely incomparable as facts if one is a tower in Paris and the other a
    tower in Dubai. Two currency figures in GBP are not comparable if one is revenue and the
    other bookings — which is exactly the pair a customer's own documents will contain.

    So comparability requires a shared subject noun, with unit, scale and locator words
    excluded from the comparison so they cannot manufacture a match.
    """
    return bool(a.context & b.context)


def _is_clause_number(num_text: str, scale: str | None, unit: str | None, currency: str | None) -> bool:
    """A bare `14.3` with no unit, scale or currency is a clause or section number.

    Contract clauses open the line they number ("14.3 The Supplier's aggregate liability…"),
    so there is no preceding "clause" keyword for the locator guard to catch. Left alone they
    parse as decimals, and MP-10 then reports clause 14.3 as contradicting clause 14.1 by
    1.4% — a finding that is confident, precise and meaningless.

    Genuine decimals in this domain carry something with them: a scale ("2.8 billion"), a unit
    ("0.005 g", "33 percent") or a currency. The cost of this rule is a bare ratio like
    "the ratio was 1.5", which is rare and worth trading away.
    """
    if scale or unit or currency:
        return False
    if "." not in num_text or "," in num_text:
        return False
    whole, _, frac = num_text.partition(".")
    return whole.isdigit() and len(whole) <= 2 and len(frac) <= 2


def _is_bare_year(num_text: str, scale: str | None, unit: str | None) -> bool:
    """A bare 1789 or 2027 is a date, not a measurement. Years belong to the temporal
    checker; treating them as quantities produces nonsense like "1789 differs from 1889
    by 5%", which materially understates a century-wide error."""
    if scale or unit:
        return False
    if "," in num_text or "." in num_text:
        return False
    try:
        value = int(num_text)
    except ValueError:
        return False
    return 1000 <= value <= 2999


def extract_quantities(text: str, *, include_years: bool = False) -> list[Quantity]:
    out: list[Quantity] = []
    for match in _QTY_RE.finditer(text):
        num_text = match.group("num")
        scale_text = (match.group("scale") or "").lower()
        unit_text = (match.group("unit") or "").lower().replace(" ", "")
        symbol = match.group("sym")
        code = (match.group("code") or "").lower()

        # A number glued to a hyphen is a fragment of an identifier or a range, not a
        # measurement: REF-TALLEST-01, MAT-NW-XYZ-9999, the "1" in a "3-1" scoreline.
        # Treating these as quantities is how a document ID ends up "contradicting" a
        # squad size.
        prev_char = text[match.start() - 1] if match.start() > 0 else ""
        if prev_char == "-":
            continue

        prev_word = _PRECEDING_WORD_RE.search(text[max(0, match.start() - 24) : match.start()])
        if prev_word and prev_word.group(1).lower() in _LOCATOR_WORDS:
            continue

        if _is_bare_year(num_text, scale_text or None, unit_text or None):
            if not include_years:
                continue
            out.append(
                Quantity(
                    raw=match.group(0).strip(),
                    value=float(num_text),
                    dimension="year",
                    start=match.start(),
                    end=match.end(),
                    context=_context_words(text, match.start(), match.end()),
                )
            )
            continue

        try:
            value = float(num_text.replace(",", ""))
        except ValueError:
            continue

        currency: str | None = None
        if symbol:
            currency = _CURRENCY_SYMBOLS.get(symbol)
        elif code in _CURRENCY_CODES:
            currency = code.upper()

        # "5 m" is ambiguous: five million, or five metres? Resolve it by whether money is in
        # play. "$4.2B" and "GBP 5m" are scales; a bare "5 m" is a unit. Guessing scale by
        # default would silently multiply a distance by a million.
        if len(scale_text) == 1 and currency is None:
            if not unit_text and scale_text.lower() in _UNITS:
                unit_text = scale_text.lower()
            scale_text = ""

        if _is_clause_number(num_text, scale_text or None, unit_text or None, currency):
            continue

        if scale_text:
            value *= _SCALES.get(scale_text, 1.0)

        if currency:
            dimension = "currency"
        elif unit_text in ("%", "percent", "percent", "percent"):
            dimension = "percent"
        elif unit_text in _UNITS:
            dimension, factor = _UNITS[unit_text]
            value *= factor
        else:
            dimension = "count"

        prefix = text[max(0, match.start() - 22) : match.start()]
        cmp_match = _COMPARATOR_RE.search(prefix.strip())
        comparator = _COMPARATORS[cmp_match.group("cmp").lower()] if cmp_match else "="

        out.append(
            Quantity(
                raw=match.group(0).strip(),
                value=value,
                dimension=dimension,
                currency=currency,
                comparator=comparator,
                start=match.start(),
                end=match.end(),
                context=_context_words(text, match.start(), match.end()),
            )
        )
    return out


def relative_difference(a: float, b: float) -> float:
    scale = max(abs(a), abs(b))
    if scale == 0:
        return 0.0
    return abs(a - b) / scale


def severity_for(diff: float) -> str:
    """Thresholds are configuration; these defaults are tuned so that a rounding
    difference is not an alarm and a doubled figure is not a footnote."""
    if diff <= 0.005:
        return "MATCH"
    if diff <= 0.05:
        return "MINOR"
    if diff <= 0.25:
        return "MODERATE"
    return "SEVERE"


@dataclass
class QuantityComparison:
    claim: Quantity
    evidence: Quantity
    severity: str
    diff: float
    satisfied: bool
    detail: str


def compare_quantities(
    claim_text: str, evidence_text: str
) -> tuple[list[QuantityComparison], list[Quantity]]:
    """Compares every quantity in the claim against same-dimension quantities in the
    evidence, keeping the closest match per claim quantity.

    Closest-match matters: a document may legitimately contain several figures, and the
    honest question is whether *any* of them supports the claim — not whether the first
    one does.
    """
    claim_qs = extract_quantities(claim_text)
    evidence_qs = extract_quantities(evidence_text)
    comparisons: list[QuantityComparison] = []

    for cq in claim_qs:
        candidates = [
            eq
            for eq in evidence_qs
            if eq.dimension == cq.dimension and shares_measure(cq, eq)
        ]
        if cq.dimension == "currency":
            # Only compare like currencies; GBP 2.8bn vs USD 4.2bn is not a numeric
            # comparison, it is a units mismatch, and saying otherwise would be wrong.
            same = [eq for eq in candidates if eq.currency == cq.currency]
            candidates = same or [eq for eq in candidates if eq.currency is None]
        if not candidates:
            continue

        best = min(candidates, key=lambda eq: relative_difference(cq.value, eq.value))
        diff = relative_difference(cq.value, best.value)
        severity = severity_for(diff)

        if cq.comparator == ">":
            satisfied = best.value > cq.value
            detail = (
                f"claim asserts more than {cq.display}; source states {best.display}"
                if not satisfied
                else f"claim asserts more than {cq.display}; source states {best.display}, consistent"
            )
        elif cq.comparator == ">=":
            satisfied = best.value >= cq.value
            detail = f"claim asserts at least {cq.display}; source states {best.display}"
        elif cq.comparator == "<":
            satisfied = best.value < cq.value
            detail = f"claim asserts less than {cq.display}; source states {best.display}"
        elif cq.comparator == "<=":
            satisfied = best.value <= cq.value
            detail = f"claim asserts at most {cq.display}; source states {best.display}"
        elif cq.comparator == "~":
            satisfied = severity in ("MATCH", "MINOR")
            detail = f"claim approximates {cq.display}; source states {best.display}"
        else:
            satisfied = severity == "MATCH"
            detail = (
                f"claim states {cq.display}; source states {best.display}"
                if not satisfied
                else f"claim states {cq.display}, matching the source"
            )

        comparisons.append(
            QuantityComparison(
                claim=cq,
                evidence=best,
                severity="MATCH" if satisfied and severity == "MATCH" else severity,
                diff=round(diff, 6),
                satisfied=satisfied,
                detail=detail,
            )
        )

    return comparisons, claim_qs
