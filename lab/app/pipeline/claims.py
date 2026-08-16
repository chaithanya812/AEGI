"""MP-04 — Claim Extraction, and MP-05 — Claim Classification.

You cannot fact-check a paragraph, only a proposition. So the output is broken into
individually checkable assertions, each with its own span in the original text.

Two design commitments here that the rest of the pipeline depends on:

**Spans are verified, not trusted.** The model proposes claims; a deterministic post-pass
requires each one to be findable in the actual output text. A "claim" the extractor
invented would otherwise get its own evidence lookup and its own verdict, and the lab would
be hallucinating about hallucinations. Anything unlocatable is dropped and the sentence it
came from is used instead.

**Sentence segmentation is the deterministic floor.** If the model call fails entirely,
extraction falls back to one claim per sentence. Extraction never blocks a run — the worst
case is coarser claims, not no verdict.

**Non-checkable claims are identified by rule, before any model sees them.** MP-05 is
explicit that an opinion needs no evidence and must never be flagged unsupported. The
screenshots that motivated this build got exactly this wrong: "my name might be mark" was
reported as *confidently wrong*, when it is a hedged personal statement that no corpus can
falsify. A validator that cries wolf on someone's own name teaches people to ignore it,
which is worse than having no validator. Hence the rules run first and win.
"""

from __future__ import annotations

import re
from typing import Any

from ..adapters.base import ModelError
from ..adapters.gemini import GeminiAdapter
from ..contracts import NON_CHECKABLE, Claim, ClaimType, Span
from .quantities import extract_quantities
from .temporal import years_in

# --- sentence segmentation ---------------------------------------------------

#: Abbreviations whose trailing period is not a sentence end. Checked in code rather than
#: in a lookbehind, because Python's `re` requires fixed-width lookbehind and these are not.
_ABBREVIATIONS = frozenset(
    """mr mrs ms dr prof sr jr st no vs etc e.g i.e approx inc ltd llc plc corp co
    fig cf al ibid rev gen col capt sgt hon jan feb mar apr jun jul aug sep sept oct
    nov dec u.s u.k p.m a.m""".split()
)

_TERMINATOR_RE = re.compile(r"[.!?]+[\)\]\"'”’]?")
_WORD_BEFORE_RE = re.compile(r"([A-Za-z0-9\.]+)\s*$")


def _is_sentence_boundary(text: str, start: int, end: int) -> bool:
    """Decide whether the terminator spanning [start, end) really ends a sentence."""
    # A period between digits is a decimal: "2.8 billion", "clause 14.3".
    if start > 0 and text[start] == "." and text[start - 1].isdigit():
        nxt = text[end : end + 1]
        if nxt.isdigit():
            return False

    word_match = _WORD_BEFORE_RE.search(text[:start])
    if word_match:
        word = word_match.group(1).lower().rstrip(".")
        if word in _ABBREVIATIONS:
            return False
        # A single capital is an initial: "J. Smith".
        if len(word) == 1 and word_match.group(1).isupper():
            return False

    # What follows must look like a new sentence, or be the end of the text.
    rest = text[end:]
    if not rest.strip():
        return True
    stripped = rest.lstrip()
    if len(rest) == len(stripped):
        return False  # no whitespace after the terminator — mid-token
    first = stripped[0]
    return first.isupper() or first.isdigit() or first in "\"'“‘(["


def split_sentences(text: str) -> list[tuple[str, int, int]]:
    """Returns (sentence, start, end) with real offsets into ``text``.

    Offsets are what make MP-04's grounding post-pass possible, so they are computed here
    rather than reconstructed by searching later.

    Lowercase-after-period input is common in the wild ("... over 500 meters. but i think
    ...") so a lowercase continuation is treated as a boundary too when the terminator is
    followed by whitespace and the preceding token is not an abbreviation.
    """
    out: list[tuple[str, int, int]] = []
    cursor = 0

    def push(end: int) -> None:
        raw = text[cursor:end]
        stripped = raw.strip()
        if stripped:
            offset = raw.index(stripped[0])
            out.append((stripped, cursor + offset, cursor + offset + len(stripped)))

    for match in _TERMINATOR_RE.finditer(text):
        start, end = match.start(), match.end()
        if end <= cursor:
            continue
        if not _is_sentence_boundary(text, start, end):
            # Lowercase continuation after real whitespace still ends a sentence, as long
            # as the preceding token is not an abbreviation and it is not a decimal.
            rest = text[end:]
            word_match = _WORD_BEFORE_RE.search(text[:start])
            word = (word_match.group(1).lower().rstrip(".") if word_match else "")
            decimal = (
                start > 0
                and text[start] == "."
                and text[start - 1].isdigit()
                and text[end : end + 1].isdigit()
            )
            if not (rest[:1].isspace() and rest.strip() and word not in _ABBREVIATIONS and not decimal):
                continue
        push(end)
        cursor = end

    push(len(text))
    return out


# --- MP-05 deterministic classification --------------------------------------

#: First-person stance markers. These make a sentence an opinion regardless of content.
_OPINION_RE = re.compile(
    r"\b(i think|i believe|i feel|i reckon|i guess|i'd say|i would say|in my (?:view|opinion)|"
    r"my (?:view|opinion) is|personally|imo|imho|it seems to me|i suspect|i assume)\b",
    re.IGNORECASE,
)

#: Epistemic hedges. These do NOT make a claim unfalsifiable — a hedged claim can still be
#: wrong — but they lower *expressed* confidence, which is what the false-certainty
#: detector compares against evidence. Being wrong tentatively is a different failure from
#: being wrong confidently, and conflating them is how a validator loses its audience.
_HEDGE_RE = re.compile(
    r"\b(might|maybe|perhaps|possibly|probably|likely|could be|may be|arguably|"
    r"apparently|reportedly|allegedly|i think|i believe|not sure|unsure|"
    r"as far as i know|roughly|approximately|about|around|some say)\b",
    re.IGNORECASE,
)

#: Statements about the speaker that no external corpus can adjudicate.
_PERSONAL_RE = re.compile(
    r"\b(my name|i am called|i'm called|i live|my address|my email|my phone|my birthday|"
    r"my favourite|my favorite|i was born|my job|i work at|my company is)\b",
    re.IGNORECASE,
)

_RECOMMEND_RE = re.compile(
    r"\b(should|ought to|recommend|advise|suggest|must consider|we propose|best to)\b",
    re.IGNORECASE,
)
_PREDICT_RE = re.compile(
    r"\b(will|shall|going to|expected to|forecast|projected|by 20\d{2} there|predict)\b",
    re.IGNORECASE,
)
_INSTRUCTION_RE = re.compile(r"^\s*(please\s+)?[a-z]+(\s+\w+){0,6}\s*$", re.IGNORECASE)
_ATTRIBUTION_RE = re.compile(
    r"\b(invented|designed|built|created|produced|founded|written by|directed by|"
    r"discovered|developed|made by|attributed to|awarded to|by)\b",
    re.IGNORECASE,
)


def classify(text: str) -> tuple[ClaimType, bool, bool]:
    """Returns (type, checkable, hedged). Deterministic, and it runs before any model.

    Order is deliberate: unfalsifiable categories are settled first so that no downstream
    stage can score them as wrong.
    """
    hedged = bool(_HEDGE_RE.search(text))

    if _PERSONAL_RE.search(text):
        return ClaimType.UNVERIFIABLE, False, hedged
    if _OPINION_RE.search(text):
        return ClaimType.OPINION, False, True
    if _RECOMMEND_RE.search(text):
        return ClaimType.RECOMMENDATION, False, hedged

    years = years_in(text)
    if _PREDICT_RE.search(text) and not any(y <= 2026 for y in years):
        return ClaimType.PREDICTION, False, hedged

    # From here the claim is checkable; the type only picks the evidence strategy.
    if years:
        return ClaimType.TEMPORAL, True, hedged
    if extract_quantities(text):
        return ClaimType.NUMERIC, True, hedged
    if _ATTRIBUTION_RE.search(text):
        return ClaimType.ENTITY, True, hedged
    if _INSTRUCTION_RE.match(text) and len(text.split()) <= 5:
        return ClaimType.INSTRUCTION, False, hedged
    return ClaimType.FACT, True, hedged


# --- MP-04 extraction --------------------------------------------------------

_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "quote": {
                        "type": "string",
                        "description": "Verbatim substring of the source text this claim comes from.",
                    },
                    "claim": {
                        "type": "string",
                        "description": "One self-contained assertion, pronouns resolved.",
                    },
                },
                "required": ["quote", "claim"],
            },
        }
    },
    "required": ["claims"],
}

_EXTRACTION_SYSTEM = """You split text into individually checkable assertions.

Rules:
- Each assertion must be ONE proposition. "Revenue was $94B, up 15%" is two.
- Resolve pronouns: "it grew 15%" must become "<the subject> grew 15%".
- `quote` must be an EXACT substring of the input, copied character for character.
- Do not invent assertions that are not in the text.
- Do not split a single reasonable sentence into trivial fragments.
- Include opinions and personal statements as claims; they are classified elsewhere.
- Aim for the smallest number of claims that fully covers the factual content."""


def _locate(quote: str, text: str, used: list[tuple[int, int]]) -> tuple[int, int] | None:
    """Find the quote in the text, preferring an unclaimed region.

    Whitespace is normalised for matching because models reflow text; everything else must
    match exactly, or the claim is treated as ungrounded.
    """
    if not quote:
        return None

    start = text.find(quote)
    while start != -1:
        span = (start, start + len(quote))
        if not any(span[0] < u[1] and u[0] < span[1] for u in used):
            return span
        start = text.find(quote, start + 1)

    # Second pass: whitespace-insensitive.
    pattern = re.compile(r"\s+".join(re.escape(part) for part in quote.split()), re.IGNORECASE)
    for match in pattern.finditer(text):
        span = (match.start(), match.end())
        if not any(span[0] < u[1] and u[0] < span[1] for u in used):
            return span

    match = pattern.search(text)
    return (match.start(), match.end()) if match else None


def _claims_from_sentences(text: str, limit: int) -> list[Claim]:
    claims: list[Claim] = []
    for i, (sentence, start, end) in enumerate(split_sentences(text)[:limit]):
        claim_type, checkable, hedged = classify(sentence)
        claims.append(
            Claim(
                claim_index=i,
                text=sentence,
                source_span=Span(start=start, end=end),
                claim_type=claim_type,
                checkable=checkable,
                hedged=hedged,
            )
        )
    return claims


async def extract(
    text: str, *, adapter: GeminiAdapter | None, limit: int = 12
) -> tuple[list[Claim], str, dict[str, int]]:
    """Returns (claims, how, usage). ``how`` is 'model+grounded' or 'sentences'."""
    sentences = split_sentences(text)
    if not sentences:
        return [], "empty", {}

    if adapter is None:
        return _claims_from_sentences(text, limit), "sentences", {}

    try:
        parsed, response = await adapter.generate_json(
            f"Split this text into checkable assertions.\n\n---\n{text}\n---",
            _EXTRACTION_SCHEMA,
            system=_EXTRACTION_SYSTEM,
            thinking="low",
            temperature=0.0,
        )
    except ModelError:
        return _claims_from_sentences(text, limit), "sentences", {}

    usage = {
        "prompt_tokens": response.prompt_tokens,
        "output_tokens": response.output_tokens,
        "thought_tokens": response.thought_tokens,
    }

    raw_items = (parsed or {}).get("claims") or []
    claims: list[Claim] = []
    used: list[tuple[int, int]] = []

    for item in raw_items:
        if len(claims) >= limit:
            break
        claim_text = (item.get("claim") or "").strip()
        quote = (item.get("quote") or "").strip()
        if not claim_text:
            continue

        span = _locate(quote, text, used) or _locate(claim_text, text, used)
        if span is None:
            # Ungrounded: the extractor produced something not present in the output.
            # Dropped rather than checked — see the module docstring.
            continue
        used.append(span)

        claim_type, checkable, hedged = classify(text[span[0] : span[1]] + " " + claim_text)
        claims.append(
            Claim(
                claim_index=len(claims),
                text=claim_text,
                source_span=Span(start=span[0], end=span[1]),
                claim_type=claim_type,
                checkable=checkable,
                hedged=hedged,
            )
        )

    if not claims:
        return _claims_from_sentences(text, limit), "sentences", usage

    # Any sentence the extractor ignored entirely still gets checked. Silent omission is
    # the one failure mode that would let a false statement through untouched.
    covered = [(c.source_span.start, c.source_span.end) for c in claims if c.source_span]
    for sentence, start, end in sentences:
        if len(claims) >= limit:
            break
        if any(start < c_end and c_start < end for c_start, c_end in covered):
            continue
        claim_type, checkable, hedged = classify(sentence)
        claims.append(
            Claim(
                claim_index=len(claims),
                text=sentence,
                source_span=Span(start=start, end=end),
                claim_type=claim_type,
                checkable=checkable,
                hedged=hedged,
            )
        )

    for i, claim in enumerate(claims):
        claim.claim_index = i

    return claims, "model+grounded", usage


def non_checkable_reason(claim: Claim) -> str:
    """Plain-language explanation shown in the UI. Never phrased as a failure."""
    if claim.claim_type is ClaimType.UNVERIFIABLE:
        return (
            "This is a statement about the speaker, not a claim about the world. No corpus "
            "can confirm or refute it, so it is reported as not checkable rather than wrong."
        )
    if claim.claim_type is ClaimType.OPINION:
        return (
            "This is stated as a personal view, not as a fact. Opinions need no evidence "
            "and are never scored as unsupported."
        )
    if claim.claim_type is ClaimType.RECOMMENDATION:
        return "This is advice rather than an assertion of fact, so there is nothing to verify."
    if claim.claim_type is ClaimType.PREDICTION:
        return (
            "This describes a future outcome. It cannot be verified against evidence today, "
            "so it is flagged as unverifiable rather than guessed at."
        )
    if claim.claim_type is ClaimType.INSTRUCTION:
        return "This is an instruction, not a factual claim."
    return "No falsifiable assertion in this sentence."


assert NON_CHECKABLE  # imported for the contract it documents
