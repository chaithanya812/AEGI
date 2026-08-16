"""MP-24 — Trace Engine.

Every pipeline stage emits an event. The tape the audience watches scroll down the right
of the screen is this, verbatim — not an animation on a timer. That distinction is the
whole point: the trace is the product, so it cannot be theatre.
"""

from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .contracts import Event


def new_trace_id() -> str:
    """Short, sayable out loud, and long enough not to collide within a session."""
    return "trace_" + uuid.uuid4().hex[:10]


def new_request_id() -> str:
    return "req_" + uuid.uuid4().hex[:12]


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class Tracer:
    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        self.events: list[Event] = []
        self._seq = 0
        self._t0 = time.perf_counter()

    def emit(
        self,
        stage: str,
        message: str,
        *,
        module: str | None = None,
        level: str = "info",
        data: dict[str, Any] | None = None,
        duration_ms: int | None = None,
    ) -> Event:
        self._seq += 1
        event = Event(
            seq=self._seq,
            at=utcnow_iso(),
            stage=stage,
            module=module,
            level=level,
            message=message,
            data=data,
            duration_ms=duration_ms,
        )
        self.events.append(event)
        return event

    @contextmanager
    def stage(
        self,
        stage: str,
        message: str,
        *,
        module: str | None = None,
        data: dict[str, Any] | None = None,
    ) -> Iterator[dict[str, Any]]:
        """Times a stage and lets the body attach its result to the same event.

        Anything the body writes into the yielded dict is merged into the event payload,
        so the tape line says what actually happened ("extracted 4 claims") rather than
        just that the stage ran.
        """
        started = time.perf_counter()
        sink: dict[str, Any] = {}
        try:
            yield sink
        except Exception as exc:
            self.emit(
                stage,
                f"{message} — failed: {exc}",
                module=module,
                level="error",
                data={**(data or {}), **sink, "error": str(exc)},
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            raise
        note = sink.pop("_message", None)
        self.emit(
            stage,
            note or message,
            module=module,
            level=str(sink.pop("_level", "info")),
            data={**(data or {}), **sink} or None,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )

    @property
    def elapsed_ms(self) -> int:
        return int((time.perf_counter() - self._t0) * 1000)
