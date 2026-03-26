"""Tests for Phase 4 Wave 3: OTel span integration via SubAgentSpanService."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.domain.model.agent.subagent_run import SubAgentRun, SubAgentRunStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_run(
    *,
    trace_id: str | None = None,
    parent_span_id: str | None = None,
    status: SubAgentRunStatus = SubAgentRunStatus.PENDING,
    subagent_name: str = "researcher",
    task: str = "find docs",
    conversation_id: str = "conv-001",
    run_id: str = "run-abc",
) -> SubAgentRun:
    run = SubAgentRun(
        conversation_id=conversation_id,
        subagent_name=subagent_name,
        task=task,
        run_id=run_id,
    )
    if status != SubAgentRunStatus.PENDING:
        run = run.start()
        if status == SubAgentRunStatus.COMPLETED:
            run = run.complete(summary="done")
        elif status == SubAgentRunStatus.FAILED:
            run = run.fail(error="boom")
    if trace_id is not None:
        # For non-PENDING runs we cannot call with_trace_context, so build directly
        if run.status is not SubAgentRunStatus.PENDING:
            from dataclasses import replace

            run = replace(run, trace_id=trace_id, parent_span_id=parent_span_id)
        else:
            run = run.with_trace_context(trace_id, parent_span_id)
    return run


def _make_mock_tracer() -> MagicMock:
    tracer = MagicMock()
    mock_span = MagicMock()
    mock_span.get_span_context.return_value = MagicMock(
        trace_id=0x1234567890ABCDEF1234567890ABCDEF,
        span_id=0xABCDEF1234567890,
        is_remote=False,
    )

    cm = MagicMock()
    cm.__enter__ = MagicMock(return_value=mock_span)
    cm.__exit__ = MagicMock(return_value=False)
    tracer.start_as_current_span = MagicMock(return_value=cm)
    tracer.start_span = MagicMock(return_value=mock_span)

    return tracer


def _get_service():
    from src.infrastructure.agent.subagent.span_service import SubAgentSpanService

    return SubAgentSpanService


# ---------------------------------------------------------------------------
# SubAgentSpanService — Construction & Configuration
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceConstruction:
    async def test_creates_with_default_component_name(self) -> None:
        cls = _get_service()
        svc = cls()
        run = _make_run()
        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=_make_mock_tracer(),
        ) as mock_get:
            async with svc.trace_run(run):
                pass
            mock_get.assert_called_with("subagent")

    async def test_creates_with_custom_component_name(self) -> None:
        cls = _get_service()
        svc = cls(component_name="my-agent")
        run = _make_run()
        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=_make_mock_tracer(),
        ) as mock_get:
            async with svc.trace_run(run):
                pass
            mock_get.assert_called_with("my-agent")

    async def test_trace_run_uses_tracer_when_telemetry_enabled(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        run = _make_run()
        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run) as span:
                assert span is not None

    async def test_trace_run_noop_when_telemetry_disabled(self) -> None:
        cls = _get_service()
        svc = cls()
        run = _make_run()
        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=None,
        ):
            async with svc.trace_run(run) as span:
                assert span is None


# ---------------------------------------------------------------------------
# SubAgentSpanService — trace_run context manager
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceTraceRun:
    async def test_trace_run_creates_span_with_attributes(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run(trace_id="abc123", parent_span_id="span-parent-1")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run) as span:
                assert span is mock_span

        # Verify span was created with correct name
        mock_tracer.start_as_current_span.assert_called()
        call_args = mock_tracer.start_as_current_span.call_args
        assert "subagent.execute" in call_args[0][0]

        # Verify attributes were set
        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_dict: dict[str, Any] = {}
        for call in set_attr_calls:
            key = call[0][0]
            val = call[0][1]
            attr_dict[key] = val

        assert attr_dict["subagent.name"] == "researcher"
        assert attr_dict["subagent.run_id"] == "run-abc"
        assert attr_dict["subagent.task"] == "find docs"
        assert attr_dict["subagent.conversation_id"] == "conv-001"
        assert attr_dict["subagent.trace_id"] == "abc123"

    async def test_trace_run_sets_ok_status_on_success(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run()

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run):
                pass

        mock_span.set_status.assert_called_once()
        status_arg = mock_span.set_status.call_args[0][0]
        from opentelemetry.trace import StatusCode

        assert status_arg.status_code == StatusCode.OK

    async def test_trace_run_records_exception_on_error(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run()
        test_error = RuntimeError("something broke")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ), pytest.raises(RuntimeError, match="something broke"):
            async with svc.trace_run(run):
                raise test_error

        mock_span.record_exception.assert_called_once_with(test_error)
        mock_span.set_status.assert_called_once()
        status_arg = mock_span.set_status.call_args[0][0]
        from opentelemetry.trace import StatusCode

        assert status_arg.status_code == StatusCode.ERROR

    async def test_trace_run_noop_when_telemetry_disabled(self) -> None:
        cls = _get_service()
        svc = cls()

        run = _make_run()

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=None,
        ):
            async with svc.trace_run(run) as span:
                assert span is None

    async def test_trace_run_noop_body_executes_normally(self) -> None:
        cls = _get_service()
        svc = cls()
        run = _make_run()
        executed = False

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=None,
        ):
            async with svc.trace_run(run):
                executed = True

        assert executed is True

    async def test_trace_run_includes_parent_span_id_attribute(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run(trace_id="t-1", parent_span_id="ps-99")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run):
                pass

        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_dict: dict[str, Any] = {}
        for call in set_attr_calls:
            attr_dict[call[0][0]] = call[0][1]

        assert attr_dict["subagent.parent_span_id"] == "ps-99"

    async def test_trace_run_omits_parent_span_id_when_none(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run(trace_id="t-1", parent_span_id=None)

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run):
                pass

        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_keys = [call[0][0] for call in set_attr_calls]
        assert "subagent.parent_span_id" not in attr_keys

    async def test_trace_run_with_running_status_run(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()
        mock_span = mock_tracer.start_as_current_span().__enter__()

        run = _make_run(status=SubAgentRunStatus.RUNNING, trace_id="t-2")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run) as span:
                assert span is mock_span

        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_dict: dict[str, Any] = {}
        for call in set_attr_calls:
            attr_dict[call[0][0]] = call[0][1]
        assert attr_dict["subagent.status"] == "running"

    async def test_trace_run_span_name_includes_agent_name(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()

        run = _make_run(subagent_name="code-reviewer")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ):
            async with svc.trace_run(run):
                pass

        call_args = mock_tracer.start_as_current_span.call_args
        span_name = call_args[0][0]
        assert "code-reviewer" in span_name


# ---------------------------------------------------------------------------
# SubAgentSpanService — mark_span_completed / mark_span_failed
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceMarkMethods:
    def test_mark_span_completed_sets_ok_status(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.mark_span_completed(mock_span, summary="all good", tokens_used=150)

        mock_span.set_status.assert_called_once()
        from opentelemetry.trace import StatusCode

        status_arg = mock_span.set_status.call_args[0][0]
        assert status_arg.status_code == StatusCode.OK

        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_dict: dict[str, Any] = {}
        for call in set_attr_calls:
            attr_dict[call[0][0]] = call[0][1]
        assert attr_dict["subagent.summary"] == "all good"
        assert attr_dict["subagent.tokens_used"] == 150

    def test_mark_span_completed_without_optional_fields(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.mark_span_completed(mock_span)

        mock_span.set_status.assert_called_once()
        set_attr_calls = mock_span.set_attribute.call_args_list
        attr_keys = [call[0][0] for call in set_attr_calls]
        assert "subagent.summary" not in attr_keys
        assert "subagent.tokens_used" not in attr_keys

    def test_mark_span_failed_sets_error_status(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.mark_span_failed(mock_span, error="timeout exceeded")

        mock_span.set_status.assert_called_once()
        from opentelemetry.trace import StatusCode

        status_arg = mock_span.set_status.call_args[0][0]
        assert status_arg.status_code == StatusCode.ERROR
        assert "timeout exceeded" in str(status_arg.description)

    def test_mark_span_failed_records_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()
        exc = ValueError("bad value")

        svc.mark_span_failed(mock_span, error="bad value", exception=exc)

        mock_span.record_exception.assert_called_once_with(exc)

    def test_mark_span_failed_without_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.mark_span_failed(mock_span, error="some error")

        mock_span.record_exception.assert_not_called()

    def test_mark_span_completed_ignores_none_span(self) -> None:
        cls = _get_service()
        svc = cls()
        # Should not raise
        svc.mark_span_completed(None, summary="ok")

    def test_mark_span_failed_ignores_none_span(self) -> None:
        cls = _get_service()
        svc = cls()
        # Should not raise
        svc.mark_span_failed(None, error="err")


# ---------------------------------------------------------------------------
# SubAgentSpanService — extract_trace_context
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceExtractContext:
    def test_extract_trace_context_from_current_span(self) -> None:
        cls = _get_service()
        svc = cls()

        mock_span = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.trace_id = 0x1234567890ABCDEF1234567890ABCDEF
        mock_ctx.span_id = 0xABCDEF1234567890
        mock_span.get_span_context.return_value = mock_ctx

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_current_span",
            return_value=mock_span,
        ):
            result = svc.extract_trace_context()

        assert result is not None
        trace_id, span_id = result
        assert isinstance(trace_id, str)
        assert isinstance(span_id, str)
        assert len(trace_id) > 0
        assert len(span_id) > 0

    def test_extract_trace_context_returns_none_for_invalid_span(self) -> None:
        cls = _get_service()
        svc = cls()

        from opentelemetry.trace import NonRecordingSpan, SpanContext

        noop_span = NonRecordingSpan(SpanContext(0, 0, is_remote=False))

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_current_span",
            return_value=noop_span,
        ):
            result = svc.extract_trace_context()

        assert result is None

    def test_extract_trace_context_formats_hex_correctly(self) -> None:
        cls = _get_service()
        svc = cls()

        mock_span = MagicMock()
        mock_ctx = MagicMock()
        mock_ctx.trace_id = 0x00000000000000001234567890ABCDEF
        mock_ctx.span_id = 0x00000000ABCDEF12
        mock_span.get_span_context.return_value = mock_ctx

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_current_span",
            return_value=mock_span,
        ):
            result = svc.extract_trace_context()

        assert result is not None
        trace_id, span_id = result
        assert len(trace_id) == 32
        assert len(span_id) == 16


# ---------------------------------------------------------------------------
# SubAgentSpanService — add_run_event
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceAddRunEvent:
    def test_add_run_event_adds_event_to_span(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.add_run_event(mock_span, "status_changed", {"from": "pending", "to": "running"})

        mock_span.add_event.assert_called_once()
        call_args = mock_span.add_event.call_args
        assert call_args[0][0] == "status_changed"
        assert call_args[1]["attributes"]["from"] == "pending"
        assert call_args[1]["attributes"]["to"] == "running"

    def test_add_run_event_ignores_none_span(self) -> None:
        cls = _get_service()
        svc = cls()
        # Should not raise
        svc.add_run_event(None, "test_event", {"key": "value"})

    def test_add_run_event_with_empty_attributes(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()

        svc.add_run_event(mock_span, "simple_event")

        mock_span.add_event.assert_called_once()
        call_args = mock_span.add_event.call_args
        assert call_args[0][0] == "simple_event"


# ---------------------------------------------------------------------------
# SubAgentSpanService — graceful error handling
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSubAgentSpanServiceErrorResilience:
    async def test_trace_run_handles_tracer_exception_gracefully(self) -> None:
        cls = _get_service()
        svc = cls()

        def broken_tracer(*args: Any, **kwargs: Any):
            raise RuntimeError("tracer init failed")

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            side_effect=broken_tracer,
        ):
            run = _make_run()
            async with svc.trace_run(run) as span:
                assert span is None

    async def test_trace_run_propagates_body_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_tracer = _make_mock_tracer()

        run = _make_run()

        with patch(
            "src.infrastructure.agent.subagent.span_service.get_tracer",
            return_value=mock_tracer,
        ), pytest.raises(ValueError, match="deliberate"):
            async with svc.trace_run(run):
                raise ValueError("deliberate")

    def test_mark_span_completed_handles_span_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()
        mock_span.set_attribute.side_effect = RuntimeError("otel broken")

        # Should not raise — graceful error handling
        svc.mark_span_completed(mock_span, summary="test")

    def test_mark_span_failed_handles_span_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()
        mock_span.set_status.side_effect = RuntimeError("otel broken")

        # Should not raise — graceful error handling
        svc.mark_span_failed(mock_span, error="test")

    def test_add_run_event_handles_span_exception(self) -> None:
        cls = _get_service()
        svc = cls()
        mock_span = MagicMock()
        mock_span.add_event.side_effect = RuntimeError("otel broken")

        # Should not raise — graceful error handling
        svc.add_run_event(mock_span, "event", {"k": "v"})
