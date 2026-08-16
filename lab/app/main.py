"""FastAPI surface.

One seam: the browser talks only to this. It never sees the Gemini key, never sees the
Supabase secret, and never talks to Supabase directly.

Persistence failures are reported, never fatal — see store.py for why. The certificate is
self-contained, so a verdict remains provable even when the audit log write fails.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .adapters.base import ModelError
from .adapters.gemini import GeminiAdapter
from .certs import signer, verify_certificate
from .contracts import PIPELINE_VERSION, VerifyRequest
from .pipeline import decision as decision_mod
from .pipeline import retrieval as retrieval_mod
from .pipeline import run as run_mod
from .presets import PRESETS
from .settings import LAB_DIR, settings
from .store import store

_adapter: GeminiAdapter | None = None


def adapter() -> GeminiAdapter | None:
    """None when no key is configured. The pipeline degrades to deterministic-only rather
    than failing, which is deliberate: the keyword ranker plus the date and figure checks
    still catch the headline failures with no model and no network."""
    global _adapter
    if not settings().has_model:
        return None
    if _adapter is None:
        _adapter = GeminiAdapter()
    return _adapter


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    if _adapter is not None:
        await _adapter.aclose()
    await store().aclose()


app = FastAPI(title="AI Reliability Lab", version=PIPELINE_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=4000)
    layers: dict[str, bool] | None = None
    domain: str = "general"


class CertificateRequest(BaseModel):
    certificate: dict[str, Any]


def _persistence_note(ok: bool, error: str | None) -> dict[str, Any]:
    return {"logged": ok, "error": error}


@app.get("/api/health")
async def health() -> dict[str, Any]:
    cfg = settings()
    signing = signer()
    return {
        "status": "ok",
        "pipeline_version": PIPELINE_VERSION,
        "model": {"configured": cfg.has_model, "model_id": cfg.model_id if cfg.has_model else None},
        "audit_log": {"configured": cfg.has_store},
        "signing": {
            "algorithm": "ed25519",
            "key_id": signing.key_id,
            "ephemeral": signing.ephemeral,
        },
        "corpus": retrieval_mod.corpus_summary(),
        "decision_table": decision_mod.DECISION_TABLE_VERSION,
        "layers": run_mod.DEFAULT_LAYERS,
    }


@app.get("/api/presets")
async def presets() -> dict[str, Any]:
    return {"presets": PRESETS}


@app.get("/api/corpus")
async def corpus() -> dict[str, Any]:
    """What the lab is allowed to check against. Shown in the UI on purpose — a verifier
    that will not tell you the extent of its evidence is asking for blind trust."""
    from .corpus import load_documents

    docs = [
        {
            "doc_id": d.doc_id,
            "title": d.title,
            "collection": d.collection,
            "authority_tier": d.authority_tier,
            "authority": d.authority,
            "effective_date": d.effective_date,
            "supersedes": d.supersedes,
            "matter": d.matter,
        }
        for d in load_documents()
    ]
    return {"summary": retrieval_mod.corpus_summary(), "documents": docs}


@app.get("/api/pubkey")
async def pubkey() -> dict[str, Any]:
    signing = signer()
    return {
        "algorithm": "ed25519",
        "key_id": signing.key_id,
        "public_key": signing.public_key_b64u,
        "encoding": "base64url, raw 32 bytes",
        "ephemeral": signing.ephemeral,
        "note": (
            "Certificates embed this key, so they verify without calling this endpoint. "
            "The browser checks signatures with WebCrypto — a server confirming its own "
            "signature would prove nothing."
        ),
    }


@app.post("/api/verify")
async def verify(request: VerifyRequest) -> dict[str, Any]:
    outputs = [line.strip() for line in request.outputs if line and line.strip()]
    if not outputs:
        raise HTTPException(status_code=400, detail="no outputs to verify")

    results: list[dict[str, Any]] = []
    persistence: list[dict[str, Any]] = []

    for text in outputs:
        try:
            result = await run_mod.verify_output(
                text,
                prompt=request.prompt,
                mode="verify_given",
                layers=request.layers,
                domain=request.domain,
                adapter=adapter(),
            )
        except ModelError as exc:
            raise HTTPException(status_code=502, detail=f"model error: {exc}") from exc

        payload = result.model_dump(mode="json")
        ok, error = await store().persist(payload)
        persistence.append({"trace_id": result.trace_id, **_persistence_note(ok, error)})
        results.append(payload)

    return {"runs": results, "persistence": persistence}


@app.post("/api/generate")
async def generate(request: GenerateRequest) -> dict[str, Any]:
    if adapter() is None:
        raise HTTPException(
            status_code=503,
            detail="GEMINI_API_KEY is not configured, so the lab cannot generate. "
            "Paste text into the box and verify it instead.",
        )
    try:
        result = await run_mod.generate_and_verify(
            request.prompt, layers=request.layers, domain=request.domain, adapter=adapter()
        )
    except ModelError as exc:
        raise HTTPException(status_code=502, detail=f"model error: {exc}") from exc

    payload = result.model_dump(mode="json")
    ok, error = await store().persist(payload)
    return {"runs": [payload], "persistence": [{"trace_id": result.trace_id, **_persistence_note(ok, error)}]}


@app.post("/api/verify-certificate")
async def check_certificate(request: CertificateRequest) -> dict[str, Any]:
    valid, detail = verify_certificate(request.certificate)
    return {"valid": valid, "detail": detail}


@app.get("/api/trace/{trace_id}")
async def trace(trace_id: str) -> dict[str, Any]:
    """MP-24 replay. Rebuilds a past verdict from the audit log."""
    row = await store().read_run(trace_id)
    if row is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"no logged run for {trace_id}"
                if settings().has_store
                else "the audit log is not configured, so past runs cannot be replayed"
            ),
        )
    return row


@app.get("/api/log")
async def log(limit: int = 40) -> dict[str, Any]:
    persisted = store()
    if not persisted.enabled:
        return {"enabled": False, "runs": [], "counters": {}, "detail": "audit log not configured"}
    return {
        "enabled": True,
        "runs": await persisted.recent_runs(min(max(limit, 1), 200)),
        "counters": await persisted.counters(),
    }


# --- static frontend ---------------------------------------------------------
# In production one process serves both. Locally the Vite dev server proxies /api here,
# so this mount is simply absent and that is fine.

_DIST = LAB_DIR / "web" / "dist"
if _DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    # HEAD as well as GET: platform health checks and uptime monitors probe with HEAD, and a
    # 405 on the root reads as an outage.
    @app.api_route("/{path:path}", methods=["GET", "HEAD"])
    async def spa(path: str) -> FileResponse:
        candidate = _DIST / path
        # Reject traversal before touching the filesystem — `path` is caller-controlled.
        if path and ".." not in path:
            try:
                resolved = candidate.resolve()
                resolved.relative_to(_DIST.resolve())
            except (ValueError, OSError):
                resolved = None
            if resolved is not None and resolved.is_file():
                return FileResponse(resolved)
        return FileResponse(_DIST / "index.html")
