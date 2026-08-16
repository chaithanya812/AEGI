"""MP-02 — Gemini adapter.

Talks raw REST rather than the SDK: fewer transitive dependencies (Vercel's Python
functions have a size ceiling), and the wire format stays inspectable, which matters for a
product whose whole pitch is traceability.

One piece of defensiveness worth naming: thinking control moved field names between Gemini
generations. We send `generationConfig.thinkingConfig.thinkingLevel`, and if the API
rejects it as an unknown field we retry once without it rather than failing the run. A
demo that dies because of a config key rename is worse than a demo that thinks less.
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

import httpx

from ..settings import settings
from .base import ModelError, ModelResponse

_JSON_FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)


class GeminiAdapter:
    """Thinking levels: minimal | low | medium | high.

    Generation runs at `minimal` (we want the model's unguarded first answer — that is the
    thing under test). Judge calls run at `low`/`medium`, where the reasoning is the point.
    """

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        cfg = settings()
        self.model_id = cfg.model_id
        self.embed_model_id = cfg.embed_model_id
        self._base = cfg.gemini_base
        self._key = cfg.gemini_api_key
        self._timeout = cfg.request_timeout
        self._client = client
        self._owns_client = client is None
        self._thinking_supported = True

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        if not self._key:
            raise ModelError("GEMINI_API_KEY is not set", retryable=False)
        client = await self._http()
        url = f"{self._base}/{path}"
        headers = {"x-goog-api-key": self._key, "Content-Type": "application/json"}

        last: ModelError | None = None
        for attempt in range(3):
            try:
                resp = await client.post(url, json=body, headers=headers)
            except httpx.HTTPError as exc:  # network, DNS, timeout
                last = ModelError(f"transport: {exc}", retryable=True)
            else:
                if resp.status_code < 400:
                    return resp.json()
                detail = resp.text[:400]
                # An unknown-field rejection is not worth failing over; drop thinking and retry.
                if (
                    resp.status_code == 400
                    and "thinking" in detail.lower()
                    and "thinkingConfig" in json.dumps(body)
                ):
                    self._thinking_supported = False
                    body.get("generationConfig", {}).pop("thinkingConfig", None)
                    continue
                retryable = resp.status_code in (429, 500, 502, 503, 504)
                last = ModelError(
                    f"gemini {resp.status_code}: {detail}",
                    retryable=retryable,
                    status=resp.status_code,
                )
                if not retryable:
                    raise last
                # Quotas are per minute, so the default sub-second backoff is far too
                # short — it burns all three attempts inside the same exhausted window and
                # the claim ends up UNKNOWN for a reason that had nothing to do with it.
                # Honour the server's own retry hint when it sends one.
                delay = _retry_delay(resp) or (2.5 * (2**attempt))
                await asyncio.sleep(min(delay, 20.0))
                continue
            await asyncio.sleep(0.6 * (2**attempt))

        raise last or ModelError("gemini: exhausted retries", retryable=True)

    def _gen_config(self, *, thinking: str, temperature: float, extra: dict[str, Any]) -> dict[str, Any]:
        cfg: dict[str, Any] = {"temperature": temperature, **extra}
        if self._thinking_supported and thinking:
            cfg["thinkingConfig"] = {"thinkingLevel": thinking}
        return cfg

    @staticmethod
    def _extract_text(payload: dict[str, Any]) -> tuple[str, str]:
        candidates = payload.get("candidates") or []
        if not candidates:
            feedback = payload.get("promptFeedback") or {}
            reason = feedback.get("blockReason") or "no candidates returned"
            raise ModelError(f"gemini produced nothing: {reason}", retryable=False)
        cand = candidates[0]
        stop = cand.get("finishReason") or "stop"
        parts = (cand.get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
        return text.strip(), str(stop)

    @staticmethod
    def _usage(payload: dict[str, Any]) -> dict[str, int]:
        u = payload.get("usageMetadata") or {}
        return {
            "prompt_tokens": int(u.get("promptTokenCount") or 0),
            "output_tokens": int(u.get("candidatesTokenCount") or 0),
            "thought_tokens": int(u.get("thoughtsTokenCount") or 0),
        }

    async def generate(
        self,
        prompt: str,
        *,
        system: str | None = None,
        thinking: str = "minimal",
        temperature: float = 0.4,
    ) -> ModelResponse:
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": self._gen_config(thinking=thinking, temperature=temperature, extra={}),
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        payload = await self._post(f"models/{self.model_id}:generateContent", body)
        text, stop = self._extract_text(payload)
        usage = self._usage(payload)
        return ModelResponse(text=text, model_id=self.model_id, stop_reason=stop, raw=payload, **usage)

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = None,
        thinking: str = "low",
        temperature: float = 0.0,
    ) -> tuple[Any, ModelResponse]:
        """Structured output. Still parses defensively — schema-constrained decoding is
        very good, not infallible, and a fenced block occasionally slips through."""
        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": self._gen_config(
                thinking=thinking,
                temperature=temperature,
                extra={"responseMimeType": "application/json", "responseSchema": schema},
            ),
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        last_error: ModelError | None = None
        for attempt in range(2):
            payload = await self._post(f"models/{self.model_id}:generateContent", body)
            text, stop = self._extract_text(payload)
            usage = self._usage(payload)
            response = ModelResponse(
                text=text, model_id=self.model_id, stop_reason=stop, raw=payload, **usage
            )
            try:
                return _parse_json(text), response
            except ModelError as exc:
                # Schema-constrained decoding is very good, not infallible. One malformed
                # response should not cost a claim its verdict, so retry once before
                # degrading — a claim that silently becomes UNKNOWN because of a stray
                # character is a coverage hole the user cannot see.
                last_error = exc
                if attempt == 0:
                    body["generationConfig"]["temperature"] = 0.0
        raise last_error or ModelError("structured output could not be parsed")

    async def embed(
        self, texts: list[str], *, task_type: str = "RETRIEVAL_DOCUMENT"
    ) -> list[list[float]]:
        """Batched. `FACT_VERIFICATION` is the right task type for evidence lookup —
        the question is "what would confirm or refute this", not "what is topically near"."""
        if not texts:
            return []
        cfg = settings()
        out: list[list[float]] = []
        for start in range(0, len(texts), 64):
            chunk = texts[start : start + 64]
            body = {
                "requests": [
                    {
                        "model": f"models/{self.embed_model_id}",
                        "content": {"parts": [{"text": t}]},
                        "taskType": task_type,
                        "outputDimensionality": cfg.embed_dims,
                    }
                    for t in chunk
                ]
            }
            payload = await self._post(f"models/{self.embed_model_id}:batchEmbedContents", body)
            for item in payload.get("embeddings") or []:
                out.append([float(v) for v in item.get("values") or []])
        if len(out) != len(texts):
            raise ModelError(f"embedding count mismatch: got {len(out)} for {len(texts)}")
        return out


_RETRY_DELAY_RE = re.compile(r'"retryDelay"\s*:\s*"(\d+(?:\.\d+)?)s"')


def _retry_delay(resp: httpx.Response) -> float | None:
    """Google returns a RetryInfo hint on quota errors; a Retry-After header also appears."""
    header = resp.headers.get("retry-after")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    match = _RETRY_DELAY_RE.search(resp.text)
    return float(match.group(1)) if match else None


def _parse_json(text: str) -> Any:
    text = text.strip()
    if not text:
        raise ModelError("model returned empty JSON", retryable=True)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    fence = _JSON_FENCE.search(text)
    if fence:
        try:
            return json.loads(fence.group(1))
        except json.JSONDecodeError:
            pass
    for opener, closer in (("{", "}"), ("[", "]")):
        i, j = text.find(opener), text.rfind(closer)
        if i != -1 and j > i:
            try:
                return json.loads(text[i : j + 1])
            except json.JSONDecodeError:
                continue
    raise ModelError(f"could not parse JSON from model output: {text[:200]}", retryable=True)
