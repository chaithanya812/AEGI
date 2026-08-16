"""Supabase persistence — the audit log.

Two deliberate choices:

1. **PostgREST over HTTPS, not a Postgres driver.** Vercel functions are short-lived and
   numerous; a connection-per-invocation pool against Postgres is the classic way to
   exhaust a small database. HTTP has no such problem, and needs no native wheel.

2. **A write failure never fails a run.** If the audit log is unreachable the verdict is
   still correct and still signed — the certificate is self-contained by design. We record
   the persistence failure on the response instead of throwing, because losing the demo to
   a logging outage would be absurd. The one thing we must never do is *silently* drop it,
   so the UI shows a "not logged" state.

No RLS: all access is server-side with the secret key, matching the CANVAS posture. The
browser never receives this key and never talks to Supabase directly.
"""

from __future__ import annotations

from typing import Any

import httpx

from .settings import settings


class Store:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        cfg = settings()
        self.enabled = cfg.has_store
        self._base = f"{cfg.supabase_url}/rest/v1" if cfg.has_store else ""
        self._headers = {
            "apikey": cfg.supabase_secret,
            "Authorization": f"Bearer {cfg.supabase_secret}",
            "Content-Type": "application/json",
        }
        self._client = client
        self._owns_client = client is None
        self.last_error: str | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=15.0)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _insert(self, table: str, rows: list[dict[str, Any]], *, upsert: bool = False) -> bool:
        if not self.enabled or not rows:
            return False
        headers = dict(self._headers)
        headers["Prefer"] = "return=minimal" + (",resolution=merge-duplicates" if upsert else "")
        try:
            client = await self._http()
            resp = await client.post(f"{self._base}/{table}", json=rows, headers=headers)
            if resp.status_code >= 400:
                self.last_error = f"{table}: {resp.status_code} {resp.text[:200]}"
                return False
            return True
        except httpx.HTTPError as exc:
            self.last_error = f"{table}: transport {exc}"
            return False

    async def _select(self, path: str) -> list[dict[str, Any]] | None:
        if not self.enabled:
            return None
        try:
            client = await self._http()
            resp = await client.get(f"{self._base}/{path}", headers=self._headers)
            if resp.status_code >= 400:
                self.last_error = f"select {path}: {resp.status_code} {resp.text[:200]}"
                return None
            return resp.json()
        except httpx.HTTPError as exc:
            self.last_error = f"select {path}: transport {exc}"
            return None

    # --- writes --------------------------------------------------------------

    async def write_run(self, run: dict[str, Any]) -> bool:
        rel = run["reliability"]
        dec = run["decision"]
        row = {
            "trace_id": run["trace_id"],
            "created_at": run["created_at"],
            "request_id": run["request_id"],
            "prompt": run.get("prompt"),
            "output_text": run["output_text"],
            "output_sha256": run["output_sha256"],
            "mode": run["mode"],
            "model_id": run.get("model_id"),
            "pipeline_version": run["pipeline_version"],
            "layers_enabled": run["layers_enabled"],
            "band": rel["band"],
            "score": rel["score"],
            "ledger": rel["ledger"],
            "decision": dec["outcome"],
            "risk": dec["risk"],
            "expressed_confidence": rel["expressed_confidence"],
            "supported_confidence": rel["supported_confidence"],
            "false_certainty": rel["false_certainty"],
            "safe_response": run.get("safe_response"),
            "latency_ms": run.get("latency_ms"),
            "token_usage": run.get("token_usage") or {},
            "degraded": run.get("degraded", False),
            "error": run.get("error"),
        }
        return await self._insert("runs", [row], upsert=True)

    async def write_claims(self, trace_id: str, claims: list[dict[str, Any]]) -> bool:
        rows = [
            {
                "trace_id": trace_id,
                "claim_index": c["claim_index"],
                "text": c["text"],
                "source_span": c.get("source_span"),
                "claim_type": c["claim_type"],
                "checkable": c["checkable"],
                "hedged": c.get("hedged", False),
                "status": c["status"],
                "decided_by": c["decided_by"],
                "reasoning": c.get("reasoning"),
                "evidence": c.get("evidence") or [],
                "checks": c.get("checks") or [],
                "confidence": c.get("confidence"),
            }
            for c in claims
        ]
        return await self._insert("claims", rows)

    async def write_events(self, trace_id: str, events: list[dict[str, Any]]) -> bool:
        rows = [
            {
                "trace_id": trace_id,
                "seq": e["seq"],
                "at": e["at"],
                "stage": e["stage"],
                "module": e.get("module"),
                "level": e.get("level", "info"),
                "message": e["message"],
                "data": e.get("data"),
                "duration_ms": e.get("duration_ms"),
            }
            for e in events
        ]
        return await self._insert("events", rows)

    async def write_certificate(self, cert: dict[str, Any]) -> bool:
        row = {
            "trace_id": cert["trace_id"],
            "issued_at": cert["issued_at"],
            "algorithm": cert["algorithm"],
            "key_id": cert["key_id"],
            "public_key": cert["public_key"],
            "payload": cert["payload"],
            "payload_sha256": cert["payload_sha256"],
            "signature": cert["signature"],
        }
        return await self._insert("certificates", [row], upsert=True)

    async def persist(self, run: dict[str, Any]) -> tuple[bool, str | None]:
        """Write the whole run. Order matters — claims and certificates reference runs."""
        if not self.enabled:
            return False, "audit log disabled (SUPABASE_URL / SUPABASE_SECRET_KEY unset)"
        self.last_error = None
        ok = await self.write_run(run)
        if not ok:
            return False, self.last_error
        await self.write_claims(run["trace_id"], run.get("claims") or [])
        await self.write_events(run["trace_id"], run.get("events") or [])
        if run.get("certificate"):
            await self.write_certificate(run["certificate"])
        return (self.last_error is None), self.last_error

    # --- reads ---------------------------------------------------------------

    async def read_run(self, trace_id: str) -> dict[str, Any] | None:
        """MP-24 replay: rebuild a past verdict from the log, months later."""
        runs = await self._select(f"runs?trace_id=eq.{trace_id}&select=*&limit=1")
        if not runs:
            return None
        run = runs[0]
        run["claims"] = await self._select(
            f"claims?trace_id=eq.{trace_id}&select=*&order=claim_index.asc"
        ) or []
        run["events"] = await self._select(
            f"events?trace_id=eq.{trace_id}&select=*&order=seq.asc"
        ) or []
        certs = await self._select(f"certificates?trace_id=eq.{trace_id}&select=*&limit=1")
        run["certificate"] = certs[0] if certs else None
        return run

    async def recent_runs(self, limit: int = 40) -> list[dict[str, Any]]:
        rows = await self._select(
            "runs?select=trace_id,created_at,output_text,band,score,decision,risk,"
            f"false_certainty,degraded&order=created_at.desc&limit={limit}"
        )
        return rows or []

    async def counters(self) -> dict[str, int]:
        """Cheap headline numbers for the log page."""
        out = {"total": 0, "unreliable": 0, "false_certainty": 0}
        rows = await self._select("runs?select=band,false_certainty&limit=1000")
        if rows is None:
            return out
        out["total"] = len(rows)
        out["unreliable"] = sum(1 for r in rows if r.get("band") == "UNRELIABLE")
        out["false_certainty"] = sum(1 for r in rows if r.get("false_certainty"))
        return out


_store: Store | None = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store()
    return _store
