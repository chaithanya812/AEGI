"""MP-40 / MP-42 — document parsing and structure-aware chunking.

Two collections, on purpose:

* ``reference`` — public factual records. Without these, a walk-up prompt about the Eiffel
  Tower has nothing to check against and the honest verdict is UNKNOWN for everything,
  which is a truthful but useless demo.
* ``matter`` — a fictional customer's own documents. This is where we own the ground truth
  outright, which is what makes the citation-mismatch and supersession scenarios
  deterministic rather than dependent on what the model happens to say today.

Chunks keep ``page`` and ``section``. MP-40's note is the reason: a citation that cannot
point at a page is not a citation, and MP-11 has nothing to resolve against without one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from functools import lru_cache
from pathlib import Path

from .settings import CORPUS_DIR

#: MP-07's source registry. Authority is a property of the source, set per deployment —
#: an audited account outranks a press release from the same company, and a peer-reviewed
#: paper outranks an internal wiki. These weights are configuration, not truth.
AUTHORITY_TIERS: dict[str, float] = {
    "peer_reviewed": 0.95,
    "audited_financial": 0.95,
    "official": 0.92,
    "executed_contract": 0.90,
    "encyclopaedic": 0.80,
    "internal_policy": 0.70,
    "company_statement": 0.60,
    "draft": 0.35,
}
DEFAULT_AUTHORITY = 0.40

_SECTION_RE = re.compile(r"^##\s+(?P<title>.+?)(?:\s*\{page=(?P<page>\d+)\})?\s*$", re.MULTILINE)
_MAX_CHUNK_CHARS = 1100


@dataclass
class Document:
    doc_id: str
    title: str
    collection: str
    authority_tier: str
    effective_date: str | None
    supersedes: str | None
    matter: str | None
    path: str

    @property
    def authority(self) -> float:
        return AUTHORITY_TIERS.get(self.authority_tier, DEFAULT_AUTHORITY)


@dataclass
class Chunk:
    chunk_id: str
    doc_id: str
    doc_title: str
    collection: str
    section: str
    page: int
    text: str
    authority: float
    authority_tier: str
    effective_date: str | None
    supersedes: str | None
    matter: str | None
    tokens: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "chunk_id": self.chunk_id,
            "doc_id": self.doc_id,
            "doc_title": self.doc_title,
            "collection": self.collection,
            "section": self.section,
            "page": self.page,
            "text": self.text,
            "authority": self.authority,
            "authority_tier": self.authority_tier,
            "effective_date": self.effective_date,
            "supersedes": self.supersedes,
            "matter": self.matter,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        chunk = cls(
            chunk_id=d["chunk_id"],
            doc_id=d["doc_id"],
            doc_title=d["doc_title"],
            collection=d["collection"],
            section=d["section"],
            page=int(d["page"]),
            text=d["text"],
            authority=float(d["authority"]),
            authority_tier=d.get("authority_tier", ""),
            effective_date=d.get("effective_date"),
            supersedes=d.get("supersedes"),
            matter=d.get("matter"),
        )
        chunk.tokens = tokenize(chunk.text)
        return chunk

    def recency_days(self, today: date | None = None) -> int | None:
        if not self.effective_date:
            return None
        try:
            eff = date.fromisoformat(self.effective_date)
        except ValueError:
            return None
        return max(0, ((today or date.today()) - eff).days)


_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9\-\.']*")

#: Kept short deliberately. Aggressive stopword lists break exact-identifier matching —
#: "clause 14.3" and "no winner exists" both depend on words a bigger list would drop.
_STOPWORDS = frozenset(
    """a an and are as at be been by for from has have in is it its of on or that the to
    was were will with this these those there their them then than""".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _parse_front_matter(raw: str) -> tuple[dict[str, str], str]:
    if not raw.startswith("---"):
        return {}, raw
    end = raw.find("\n---", 3)
    if end == -1:
        return {}, raw
    meta: dict[str, str] = {}
    for line in raw[3:end].strip().splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            meta[key.strip()] = value.strip()
    return meta, raw[end + 4 :]


def _split_long(text: str) -> list[str]:
    """Split on paragraph boundaries only. Cutting mid-sentence produces chunks that
    retrieve as nonsense and quote as a lie."""
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for para in re.split(r"\n\s*\n", text):
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) > _MAX_CHUNK_CHARS and current:
            parts.append(current)
            current = para
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts


def load_documents() -> list[Document]:
    docs: list[Document] = []
    for path in sorted(CORPUS_DIR.rglob("*.md")):
        meta, _ = _parse_front_matter(path.read_text(encoding="utf-8"))
        if not meta.get("doc_id"):
            continue
        docs.append(
            Document(
                doc_id=meta["doc_id"],
                title=meta.get("title", path.stem),
                collection=meta.get("collection", path.parent.name),
                authority_tier=meta.get("authority_tier", ""),
                effective_date=meta.get("effective_date"),
                supersedes=meta.get("supersedes"),
                matter=meta.get("matter"),
                path=str(path.relative_to(CORPUS_DIR)),
            )
        )
    return docs


def build_chunks() -> list[Chunk]:
    chunks: list[Chunk] = []
    for path in sorted(CORPUS_DIR.rglob("*.md")):
        raw = path.read_text(encoding="utf-8")
        meta, body = _parse_front_matter(raw)
        if not meta.get("doc_id"):
            continue

        doc = Document(
            doc_id=meta["doc_id"],
            title=meta.get("title", path.stem),
            collection=meta.get("collection", path.parent.name),
            authority_tier=meta.get("authority_tier", ""),
            effective_date=meta.get("effective_date"),
            supersedes=meta.get("supersedes"),
            matter=meta.get("matter"),
            path=str(path.relative_to(CORPUS_DIR)),
        )

        matches = list(_SECTION_RE.finditer(body))
        for i, match in enumerate(matches):
            start = match.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
            section_text = body[start:end].strip()
            if not section_text:
                continue
            section = match.group("title").strip()
            page = int(match.group("page") or 1)

            for part_no, part in enumerate(_split_long(section_text)):
                chunk = Chunk(
                    chunk_id=f"{doc.doc_id}#p{page}-{i}-{part_no}",
                    doc_id=doc.doc_id,
                    doc_title=doc.title,
                    collection=doc.collection,
                    section=section,
                    page=page,
                    text=part,
                    authority=doc.authority,
                    authority_tier=doc.authority_tier,
                    effective_date=doc.effective_date,
                    supersedes=doc.supersedes,
                    matter=doc.matter,
                )
                chunk.tokens = tokenize(part)
                chunks.append(chunk)
    return chunks


@lru_cache(maxsize=1)
def supersession_map() -> dict[str, str]:
    """doc_id -> the doc_id that replaced it.

    MP-12 needs this: a claim sourced from a superseded document is not false, it is
    *stale*, and stale is the dangerous case because the text reads as accurate.
    """
    out: dict[str, str] = {}
    for doc in load_documents():
        if doc.supersedes:
            out[doc.supersedes] = doc.doc_id
    return out
