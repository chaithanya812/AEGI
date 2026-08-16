"""MP-06 / MP-44 — evidence retrieval (the RAG layer).

Hybrid, and the reason is not fashion. Pure vector search is bad at exact identifiers —
"clause 14.3", "GBP 2.8 billion", "MAT-NW-AMD1-2024" — and pure keyword search is bad at
paraphrase. Verification needs both: the numeric claims live or die on exact tokens, the
prose claims on meaning. Fused with reciprocal rank fusion, which needs no score
calibration between the two very differently-scaled rankers.

The important distinction from ordinary RAG, and it is easy to miss: **this is not
retrieval for answering.** The question is not "what is relevant to the user's query" but
"what would confirm or refute this specific proposition". So each claim gets its own
rewritten query, driven by its type from MP-05. Retrieving what is topically nearby is how
you end up confirming a claim with a document that merely mentions the same nouns.

BM25 is hand-rolled rather than pulled in as a dependency: the corpus is small enough that
it costs nothing, one less wheel to ship to a size-capped serverless runtime, and — most
usefully — an auditor can read the ranking function.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache

from ..adapters.base import ModelError
from ..adapters.gemini import GeminiAdapter
from ..contracts import ClaimType, EvidenceItem
from ..corpus import Chunk, build_chunks, tokenize
from ..settings import INDEX_PATH, settings
from ..trace import utcnow_iso

_K1 = 1.4
_B = 0.75
_RRF_K = 60


@dataclass
class Index:
    chunks: list[Chunk]
    vectors: list[list[float]] | None
    embed_model: str | None
    embed_dims: int | None

    # BM25 statistics, computed on load — trivially cheap at this corpus size.
    df: dict[str, int] = None  # type: ignore[assignment]
    avg_len: float = 0.0

    def __post_init__(self) -> None:
        self.df = {}
        total = 0
        for chunk in self.chunks:
            total += len(chunk.tokens)
            for term in set(chunk.tokens):
                self.df[term] = self.df.get(term, 0) + 1
        self.avg_len = (total / len(self.chunks)) if self.chunks else 0.0

    @property
    def has_vectors(self) -> bool:
        return bool(self.vectors) and len(self.vectors or []) == len(self.chunks)


@lru_cache(maxsize=1)
def index() -> Index:
    """Loads the prebuilt index if present, else falls back to keyword-only.

    Missing vectors is a degradation, not a failure: BM25 alone still finds the exact
    figures and clause numbers the deterministic checks need, so the demo keeps working
    with no embedding call and no network.
    """
    if INDEX_PATH.exists():
        try:
            data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
            chunks = [Chunk.from_dict(c) for c in data["chunks"]]
            vectors = data.get("vectors")
            return Index(
                chunks=chunks,
                vectors=vectors,
                embed_model=data.get("embed_model"),
                embed_dims=data.get("embed_dims"),
            )
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt index — rebuild from source below
    return Index(chunks=build_chunks(), vectors=None, embed_model=None, embed_dims=None)


def bm25(query_tokens: list[str], idx: Index, limit: int = 30) -> list[tuple[int, float]]:
    n = len(idx.chunks)
    if not n or not query_tokens:
        return []
    scored: list[tuple[int, float]] = []
    for i, chunk in enumerate(idx.chunks):
        length = len(chunk.tokens) or 1
        freq: dict[str, int] = {}
        for term in chunk.tokens:
            freq[term] = freq.get(term, 0) + 1
        score = 0.0
        for term in query_tokens:
            tf = freq.get(term)
            if not tf:
                continue
            df = idx.df.get(term, 0)
            idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
            score += idf * (tf * (_K1 + 1)) / (tf + _K1 * (1 - _B + _B * length / idx.avg_len))
        if score > 0:
            scored.append((i, score))
    scored.sort(key=lambda p: p[1], reverse=True)
    return scored[:limit]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = na = nb = 0.0
    for x, y in zip(a, b):
        dot += x * y
        na += x * x
        nb += y * y
    if na <= 0 or nb <= 0:
        return 0.0
    return dot / math.sqrt(na * nb)


def vector_search(query_vec: list[float], idx: Index, limit: int = 30) -> list[tuple[int, float]]:
    if not idx.has_vectors:
        return []
    scored = [(i, _cosine(query_vec, vec)) for i, vec in enumerate(idx.vectors or [])]
    scored = [p for p in scored if p[1] > 0.15]
    scored.sort(key=lambda p: p[1], reverse=True)
    return scored[:limit]


def reciprocal_rank_fusion(
    rankings: list[list[tuple[int, float]]], weights: list[float] | None = None
) -> list[tuple[int, float]]:
    """RRF needs no score normalisation between rankers, which is the point — BM25 scores
    and cosine similarities are not on comparable scales and pretending otherwise is how
    hybrid retrieval quietly becomes whichever ranker has the bigger numbers."""
    weights = weights or [1.0] * len(rankings)
    fused: dict[int, float] = {}
    for ranking, weight in zip(rankings, weights):
        for rank, (idx_, _score) in enumerate(ranking):
            fused[idx_] = fused.get(idx_, 0.0) + weight / (_RRF_K + rank + 1)
    out = sorted(fused.items(), key=lambda p: p[1], reverse=True)
    return out


#: Query rewriting per claim type. A numeric claim wants the number and its subject; a
#: temporal claim wants the date terms; an entity claim wants the proper nouns.
_STRATEGY_HINTS: dict[ClaimType, str] = {
    ClaimType.NUMERIC: "figure value amount total",
    ClaimType.TEMPORAL: "date year completed effective superseded",
    ClaimType.ENTITY: "who designed built produced attributed",
    ClaimType.FACT: "",
}

_NUM_RE = re.compile(r"\d[\d,\.]*")
_PROPER_RE = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")


def rewrite_query(claim_text: str, claim_type: ClaimType) -> str:
    """Targets the proposition, not the user's question."""
    hint = _STRATEGY_HINTS.get(claim_type, "")
    parts = [claim_text]
    # Numbers and proper nouns are the highest-signal tokens for verification and must not
    # be diluted, so they are repeated to weight them in the keyword ranker.
    numbers = _NUM_RE.findall(claim_text)
    propers = _PROPER_RE.findall(claim_text)
    if numbers:
        parts.append(" ".join(numbers))
    if propers:
        parts.append(" ".join(propers[:6]))
    if hint:
        parts.append(hint)
    return " ".join(parts)


async def retrieve_for_claim(
    claim_text: str,
    claim_type: ClaimType,
    *,
    adapter: GeminiAdapter | None = None,
    top_k: int = 4,
    candidate_k: int = 24,
    today: date | None = None,
) -> tuple[list[EvidenceItem], str]:
    """Returns the evidence set and which retrieval path produced it.

    MP-45's job (pass four good chunks, not twenty mediocre ones) is folded in here as a
    relevance cutoff: everything passed forward gets verified downstream, and junk in the
    context burns judge budget while widening the surface for a wrong verdict.
    """
    idx = index()
    if not idx.chunks:
        return [], "empty"

    query = rewrite_query(claim_text, claim_type)
    keyword = bm25(tokenize(query), idx, limit=candidate_k)

    semantic: list[tuple[int, float]] = []
    mode = "bm25"
    if adapter is not None and idx.has_vectors:
        try:
            vecs = await adapter.embed([query], task_type="FACT_VERIFICATION")
            if vecs:
                semantic = vector_search(vecs[0], idx, limit=candidate_k)
                mode = "hybrid" if keyword else "vector"
        except ModelError:
            mode = "bm25"  # degrade, never fail the run over retrieval

    if semantic:
        fused = reciprocal_rank_fusion([keyword, semantic], weights=[1.0, 1.0])
    else:
        fused = [(i, 1.0 / (_RRF_K + r + 1)) for r, (i, _s) in enumerate(keyword)]

    if not fused:
        return [], mode

    best = fused[0][1] or 1.0
    now = utcnow_iso()
    items: list[EvidenceItem] = []
    for chunk_idx, score in fused[:top_k]:
        # Relevance cutoff relative to the top hit — a long tail of weak matches is worse
        # than a short list, because each one is another chance to "support" a false claim.
        if score < best * 0.35:
            break
        chunk = idx.chunks[chunk_idx]
        items.append(
            EvidenceItem(
                doc_id=chunk.doc_id,
                doc_title=chunk.doc_title,
                collection=chunk.collection,
                matter=chunk.matter,
                section=chunk.section,
                page=chunk.page,
                quote=chunk.text.strip()[:900],
                authority=chunk.authority,
                recency_days=chunk.recency_days(today),
                relevance=round(min(1.0, score / best), 4),
                score=round(score, 6),
                retrieved_by=mode,
                retrieved_at=now,
            )
        )
    return items, mode


def corpus_summary() -> dict:
    idx = index()
    collections: dict[str, int] = {}
    docs: set[str] = set()
    for chunk in idx.chunks:
        collections[chunk.collection] = collections.get(chunk.collection, 0) + 1
        docs.add(chunk.doc_id)
    return {
        "documents": len(docs),
        "chunks": len(idx.chunks),
        "collections": collections,
        "vectors": idx.has_vectors,
        "embed_model": idx.embed_model,
        "embed_dims": idx.embed_dims,
        "retrieval": "hybrid (bm25 + vector, RRF)" if idx.has_vectors else "bm25 only",
    }


def _reset_index_cache() -> None:
    index.cache_clear()
