from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any

from opentelemetry.trace import NonRecordingSpan, Status, StatusCode

from src.infrastructure.telemetry.config import get_tracer
from src.infrastructure.telemetry.tracing import get_current_span

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from opentelemetry.trace import Span

    from src.domain.model.agent.subagent_run import SubAgentRun

logger = logging.getLogger(__name__)


class SubAgentSpanService:
    __slots__ = ("_component_name",)

    def __init__(self, component_name: str = "subagent") -> None:
        self._component_name = component_name

    def _get_tracer(self) -> Any:  # noqa: ANN401
        return get_tracer(self._component_name)

    @asynccontextmanager
    async def trace_run(self, run: SubAgentRun) -> AsyncIterator[Span | None]:
        try:
            tracer = self._get_tracer()
        except Exception:
            logger.debug("Failed to obtain tracer, running without tracing")
            yield None
            return

        if tracer is None:
            yield None
            return

        span_name = f"subagent.execute/{run.subagent_name}"

        with tracer.start_as_current_span(span_name) as span:
            span.set_attribute("subagent.name", run.subagent_name)
            span.set_attribute("subagent.run_id", run.run_id)
            span.set_attribute("subagent.task", run.task)
            span.set_attribute("subagent.conversation_id", run.conversation_id)
            span.set_attribute("subagent.status", run.status.value)

            if run.trace_id is not None:
                span.set_attribute("subagent.trace_id", run.trace_id)
            if run.parent_span_id is not None:
                span.set_attribute("subagent.parent_span_id", run.parent_span_id)

            try:
                yield span
                span.set_status(Status(StatusCode.OK))
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                raise

    def mark_span_completed(
        self,
        span: Span | None,
        *,
        summary: str | None = None,
        tokens_used: int | None = None,
        execution_time_ms: int | None = None,
    ) -> None:
        if span is None:
            return
        try:
            if summary is not None:
                span.set_attribute("subagent.summary", summary)
            if tokens_used is not None:
                span.set_attribute("subagent.tokens_used", tokens_used)
            if execution_time_ms is not None:
                span.set_attribute("subagent.execution_time_ms", execution_time_ms)
            span.set_status(Status(StatusCode.OK))
        except Exception:
            logger.debug("Failed to mark span completed", exc_info=True)

    def mark_span_failed(
        self,
        span: Span | None,
        *,
        error: str,
        exception: Exception | None = None,
    ) -> None:
        if span is None:
            return
        try:
            if exception is not None:
                span.record_exception(exception)
            span.set_status(Status(StatusCode.ERROR, error))
        except Exception:
            logger.debug("Failed to mark span failed", exc_info=True)

    def add_run_event(
        self,
        span: Span | None,
        event_name: str,
        attributes: dict[str, Any] | None = None,
    ) -> None:
        if span is None:
            return
        try:
            span.add_event(event_name, attributes=attributes or {})
        except Exception:
            logger.debug("Failed to add run event to span", exc_info=True)

    def extract_trace_context(self) -> tuple[str, str] | None:
        span = get_current_span()
        if isinstance(span, NonRecordingSpan):
            return None

        try:
            ctx = span.get_span_context()
            if ctx.trace_id == 0:
                return None
            trace_id = format(ctx.trace_id, "032x")
            span_id = format(ctx.span_id, "016x")
            return trace_id, span_id
        except Exception:
            logger.debug("Failed to extract trace context", exc_info=True)
            return None
