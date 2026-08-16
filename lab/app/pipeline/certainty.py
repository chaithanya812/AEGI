"""False-certainty detection.

Not a Sentinel module — this one is additional, and it is the most distinctive thing in the
lab. Everything else asks "is this claim true?". This asks a different question:

    **How confident did the text sound, and how confident was it entitled to sound?**

The gap is the finding. A wrong answer delivered tentatively is a very different failure
from the same wrong answer delivered flatly, because only the second one gets acted on
without checking. Conversely, a *correct* answer smothered in hedges is its own problem —
it trains users to discount the system.

Expressed confidence is measured from the prose, deterministically: hedges, qualifiers and
attributions lower it; bare declaratives raise it. Supported confidence comes from the
verdict ledger. Neither number is a model's self-report, which matters — asking a model how
confident it is just produces more fluent text, and the literature is consistent that
stated confidence tracks accuracy poorly.
"""

from __future__ import annotations

import re

from ..contracts import Claim, Confidence, Support

#: Flat, unqualified assertion markers — the grammar of certainty.
_EMPHATIC_RE = re.compile(
    r"\b(definitely|certainly|clearly|obviously|undoubtedly|without doubt|in fact|"
    r"the fact is|always|never|proven|confirmed|established|indeed|of course|"
    r"it is well known|everyone knows|remains the|is the)\b",
    re.IGNORECASE,
)

_HEDGE_RE = re.compile(
    r"\b(might|may|maybe|perhaps|possibly|probably|likely|unlikely|could|appears|seems|"
    r"suggests|approximately|roughly|around|about|arguably|reportedly|allegedly|"
    r"i think|i believe|as far as i know|to my knowledge|not certain|unclear|"
    r"reportedly|purportedly|some say|it is said)\b",
    re.IGNORECASE,
)

_ATTRIBUTION_RE = re.compile(
    r"\b(according to|per the|as stated in|cites|citing|source[sd]?\s|reported by)\b",
    re.IGNORECASE,
)


def expressed_confidence(text: str, claims: list[Claim]) -> tuple[Confidence, str]:
    """What the writing claims for itself."""
    words = max(1, len(text.split()))
    hedges = len(_HEDGE_RE.findall(text))
    emphatics = len(_EMPHATIC_RE.findall(text))
    attributions = len(_ATTRIBUTION_RE.findall(text))

    checkable = [c for c in claims if c.checkable]
    hedged_share = (
        sum(1 for c in checkable if c.hedged) / len(checkable) if checkable else 0.0
    )

    # Density per 100 words keeps short and long outputs comparable.
    hedge_density = hedges / words * 100

    if hedged_share >= 0.6 or hedge_density >= 6:
        level = Confidence.LOW
        note = f"heavily qualified — {hedges} hedging expression(s) across {words} words"
    elif hedged_share >= 0.25 or hedge_density >= 2.5:
        level = Confidence.MEDIUM
        note = f"partly qualified — {hedges} hedging expression(s), some claims hedged"
    else:
        level = Confidence.HIGH
        note = (
            f"stated flatly — no meaningful hedging"
            if not hedges
            else f"stated flatly — {hedges} hedge(s) but {len(checkable)} bare assertion(s)"
        )
        if emphatics:
            note += f", plus {emphatics} emphatic marker(s)"

    if attributions and level is Confidence.HIGH:
        note += "; confidence is attributed to a source rather than asserted directly"

    return level, note


def supported_confidence(claims: list[Claim]) -> tuple[Confidence, str]:
    """What the evidence actually entitles the text to."""
    checkable = [c for c in claims if c.checkable]
    if not checkable:
        return Confidence.MEDIUM, "nothing checkable in this output"

    total = len(checkable)
    supported = sum(1 for c in checkable if c.status is Support.SUPPORTED)
    bad = sum(
        1
        for c in checkable
        if c.status in (Support.CONTRADICTED, Support.UNSUPPORTED)
    )
    unknown = sum(1 for c in checkable if c.status is Support.UNKNOWN)

    if bad:
        return (
            Confidence.LOW,
            f"{bad} of {total} checkable claim(s) unsupported or contradicted by the evidence",
        )
    if unknown / total > 0.5:
        return (
            Confidence.LOW,
            f"{unknown} of {total} checkable claim(s) have no evidence either way",
        )
    if supported == total:
        return Confidence.HIGH, f"all {total} checkable claim(s) supported by evidence"
    return (
        Confidence.MEDIUM,
        f"{supported} of {total} checkable claim(s) fully supported; the rest are partial or unknown",
    )


_RANK = {Confidence.LOW: 0, Confidence.MEDIUM: 1, Confidence.HIGH: 2}


def assess(text: str, claims: list[Claim]) -> tuple[Confidence, Confidence, bool, str]:
    """Returns (expressed, supported, false_certainty, note)."""
    exp, exp_note = expressed_confidence(text, claims)
    sup, sup_note = supported_confidence(claims)

    gap = _RANK[exp] - _RANK[sup]
    false_certainty = gap >= 2 or (gap >= 1 and sup is Confidence.LOW)

    # The note explains; it does not restate the two levels. Callers (the UI notice and
    # MP-16's message) already print those, and having both produced a sentence that said
    # "expressed MEDIUM, supported LOW" twice in a row.
    if false_certainty:
        note = f"The text {exp_note}, but {sup_note}."
    elif gap <= -1:
        note = (
            f"The text is more cautious than the evidence requires: it {exp_note}, while "
            f"{sup_note}. Over-hedging a correct answer has its own cost."
        )
    else:
        note = f"The text {exp_note}, and {sup_note}."

    return exp, sup, false_certainty, note
