"""Vercel entry point.

Vercel's Python runtime looks for an ASGI application named ``app`` in this module, so this
file only fixes the import path and re-exports the real one. All routing lives in
app/main.py, which is also what runs under uvicorn locally — one code path, two hosts.

In production Vercel serves web/dist from its CDN and this function handles /api/* only, so
the static mount inside app/main.py is simply inactive here.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402

__all__ = ["app"]
