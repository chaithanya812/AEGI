"""Build the retrieval index.

Chunks every corpus document and, if a Gemini key is available, embeds each chunk once and
caches the vectors into corpus/index.json. Committing the vectors means the deployed app
never embeds the corpus at request time, and the demo works with no embedding call at all.

    python scripts/build_corpus.py           # chunk + embed
    python scripts/build_corpus.py --no-embed  # chunk only, keyword retrieval

Missing vectors is a graceful degradation, not a failure: BM25 alone still finds the exact
figures and clause numbers that the deterministic checks depend on.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.adapters.gemini import GeminiAdapter  # noqa: E402
from app.corpus import build_chunks  # noqa: E402
from app.settings import INDEX_PATH, settings  # noqa: E402


async def main() -> int:
    embed = "--no-embed" not in sys.argv
    cfg = settings()

    chunks = build_chunks()
    if not chunks:
        print("no chunks produced — is corpus/ populated?")
        return 1

    docs = sorted({c.doc_id for c in chunks})
    collections: dict[str, int] = {}
    for chunk in chunks:
        collections[chunk.collection] = collections.get(chunk.collection, 0) + 1

    print(f"chunked {len(docs)} documents into {len(chunks)} chunks")
    for name, count in sorted(collections.items()):
        print(f"  {name}: {count} chunks")

    vectors = None
    if embed and cfg.has_model:
        adapter = GeminiAdapter()
        try:
            print(f"embedding with {cfg.embed_model_id} at {cfg.embed_dims} dims ...")
            vectors = await adapter.embed(
                [f"{c.doc_title} — {c.section}\n{c.text}" for c in chunks],
                task_type="RETRIEVAL_DOCUMENT",
            )
            # Rounded to five places: the similarity ranking is unaffected and the committed
            # index is roughly a third of the size.
            vectors = [[round(v, 5) for v in vec] for vec in vectors]
            print(f"  embedded {len(vectors)} chunks")
        except Exception as exc:
            print(f"  embedding failed ({exc}) — writing keyword-only index")
            vectors = None
        finally:
            await adapter.aclose()
    elif embed:
        print("GEMINI_API_KEY not set — writing keyword-only index")

    payload = {
        "chunks": [c.to_dict() for c in chunks],
        "vectors": vectors,
        "embed_model": cfg.embed_model_id if vectors else None,
        "embed_dims": cfg.embed_dims if vectors else None,
    }
    INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    size_kb = INDEX_PATH.stat().st_size / 1024
    print(f"wrote {INDEX_PATH.name} ({size_kb:.0f} KB, vectors={'yes' if vectors else 'no'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
