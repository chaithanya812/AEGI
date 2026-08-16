"""MP-02 — Model Adapter Layer (interface).

Every provider returns a different JSON shape and fails differently. Downstream modules
see only this interface, so swapping Gemini for a self-hosted model is one config line
rather than forty files. There is one adapter today; the interface exists so
"model-agnostic" is demonstrable rather than merely claimed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class ModelError(RuntimeError):
    """Normalised provider failure. Adapters translate their own error taxonomy into this."""

    def __init__(self, message: str, *, retryable: bool = False, status: int | None = None):
        super().__init__(message)
        self.retryable = retryable
        self.status = status


@dataclass
class ModelResponse:
    """Canonical response. Provider-specific fields are normalised away here."""

    text: str
    model_id: str
    prompt_tokens: int = 0
    output_tokens: int = 0
    thought_tokens: int = 0
    stop_reason: str = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


class ModelAdapter(Protocol):
    model_id: str

    async def generate(
        self, prompt: str, *, system: str | None = ..., thinking: str = ..., temperature: float = ...
    ) -> ModelResponse: ...

    async def generate_json(
        self,
        prompt: str,
        schema: dict[str, Any],
        *,
        system: str | None = ...,
        thinking: str = ...,
        temperature: float = ...,
    ) -> tuple[Any, ModelResponse]: ...

    async def embed(self, texts: list[str], *, task_type: str = ...) -> list[list[float]]: ...
