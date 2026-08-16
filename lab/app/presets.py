"""Demo presets.

Defined server-side so the UI, the smoke test and any future recording all use the same
list — a rehearsed demo whose script lives in three places will drift.

The first four are chosen so that a check which *cannot fail* carries the outcome: the World
Cup case turns on date arithmetic, the revenue case on a figure in a document we wrote.
"Hope the model hallucinates" fails on stage roughly one run in four, so nothing here
depends on the model cooperating.

The last two are pasted rather than generated, and both come from the screenshots that
motivated this build. `false-alarm` is there as a regression guard: the tool being compared
against reported "my name might be mark" as *confidently wrong*, and if this lab ever does
the same, that preset is how we find out.
"""

from __future__ import annotations

from typing import Any

PRESETS: list[dict[str, Any]] = [
    {
        "id": "safe",
        "label": "Clean answer",
        "tone": "green",
        "mode": "generate",
        "domain": "general",
        "prompt": "What is photosynthesis?",
        "expect": "Every checkable claim supported by the reference corpus. Band VERIFIED, decision ALLOW.",
        "carried_by": "Corpus contains a peer-reviewed process summary that entails the standard answer.",
    },
    {
        "id": "future",
        "label": "Future event",
        "tone": "red",
        "mode": "verify_given",
        "domain": "general",
        "text": (
            "Argentina won the 2027 FIFA World Cup, beating Brazil 3-1 in the final in "
            "Buenos Aires."
        ),
        "expect": (
            "CONTRADICTED on deterministic grounds — 2027 is after the reference clock and "
            "the claim asserts a completed result. No model opinion involved."
        ),
        "carried_by": (
            "Date arithmetic, MP-12. This is supplied as pasted text rather than generated, "
            "because a current model asked this question usually declines correctly — and the "
            "validator has to work on text from any model, including the ones that don't."
        ),
    },
    {
        "id": "citation",
        "label": "Citation mismatch",
        "tone": "red",
        "mode": "generate",
        "domain": "financial",
        "prompt": (
            "According to its FY2025 results, Northwind Systems reported revenue of "
            "GBP 4.2 billion. Summarise their FY2025 performance and cite the figure."
        ),
        "expect": "The cited source says GBP 2.8 billion. Caught by arithmetic, not judgement.",
        "carried_by": "Northwind exists only in our corpus, so we own the ground truth outright. MP-11.",
    },
    {
        "id": "stale",
        "label": "Superseded source",
        "tone": "amber",
        "mode": "generate",
        "domain": "legal",
        "prompt": (
            "In the Northwind Systems master services agreement, what is the cap on the "
            "supplier's indemnity liability, and does it survive termination?"
        ),
        "expect": "The 2023 text says GBP 2m and does not survive; Amendment No. 1 raised it to GBP 5m and made it survive.",
        "carried_by": "Supersession is a metadata comparison, not a reading. Accurate text, superseded fact. MP-12.",
    },
    {
        "id": "eiffel",
        "label": "Mixed paragraph",
        "tone": "red",
        "mode": "verify_given",
        "domain": "general",
        "text": (
            "The Eiffel Tower was built in 1789 by Napoleon Bonaparte as a monument to the "
            "French Revolution, and it remains the tallest structure in Europe at over 500 "
            "meters. but i think burj kahalifa is the tallest tower"
        ),
        "expect": (
            "Several claims contradicted — the height numerically, the attribution and date "
            "against the record. The final hedged clause is an opinion and is not scored as wrong."
        ),
        "carried_by": "\"over 500 meters\" vs 330 metres is a 51% numeric gap. Deterministic.",
    },
    {
        "id": "false-alarm",
        "label": "Not checkable",
        "tone": "amber",
        "mode": "verify_given",
        "domain": "general",
        "text": "my name might be mark . tom and jerry is disny show",
        "expect": (
            "First sentence: a hedged personal statement, NOT_APPLICABLE — no corpus can "
            "falsify it. Second: a real studio misattribution, CONTRADICTED. "
            "Two sentences, two different kinds of answer."
        ),
        "carried_by": "Regression guard. The tool this was compared against called the first one confidently wrong.",
    },
]


def by_id(preset_id: str) -> dict[str, Any] | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)
