"""Tests for ToolPipeline."""

from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.tools.context import ToolAbortedError, ToolContext
from src.infrastructure.agent.tools.hooks import HookDecision, HookResult, ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolEvent, ToolResult
from src.infrastructure.agent.tools.truncation import OutputTruncator


def _make_ctx() -> ToolContext:
    return ToolContext(
        session_id="s",
        message_id="m",
        call_id="c",
        agent_name="a",
        conversation_id="conv",
    )


@dataclass
class FakeTool:
    """Fake tool implementing ToolInfoProtocol."""

    name: str = "test_tool"
    permission: str | None = None
    _execute_fn: (
        Callable[..., Coroutine[Any, Any, ToolResult | str | dict | list | None]] | None
    ) = None

    async def execute(self, **kwargs: Any) -> Any:  # noqa: ANN401
        if self._execute_fn:
            return await self._execute_fn(**kwargs)
        return ToolResult(output="ok")


def _make_pipeline(
    permission_manager: MagicMock | None = None,
    doom_detector: MagicMock | None = None,
    truncator: OutputTruncator | None = None,
    hooks: ToolHookRegistry | None = None,
) -> ToolPipeline:
    if permission_manager is None:
        pm = MagicMock()
        pm.evaluate = MagicMock()
        permission_manager = pm

    if doom_detector is None:
        dd = MagicMock()
        dd.should_intervene = MagicMock(return_value=False)
        dd.record = MagicMock()
        doom_detector = dd

    if truncator is None:
        truncator = OutputTruncator(max_bytes=50 * 1024)

    if hooks is None:
        hooks = ToolHookRegistry()

    return ToolPipeline(
        permission_manager=permission_manager,
        doom_detector=doom_detector,
        truncator=truncator,
        hooks=hooks,
    )


async def _collect_events(
    pipeline: ToolPipeline, tool: FakeTool, args: dict[str, object], ctx: ToolContext
) -> list[ToolEvent]:
    events: list[ToolEvent] = []
    async for event in pipeline.execute(tool, args, ctx):
        events.append(event)
    return events


@pytest.mark.unit
class TestToolPipeline:
    """Tests for ToolPipeline execution stages."""

    async def test_happy_path_yields_started_and_completed(self) -> None:
        # Arrange
        pipeline = _make_pipeline()
        tool = FakeTool()
        ctx = _make_ctx()

        # Act
        events = await _collect_events(pipeline, tool, {}, ctx)

        # Assert
        assert len(events) == 2
        assert events[0].type == "started"
        assert events[0].tool_name == "test_tool"
        assert events[1].type == "completed"
        assert events[1].data["is_error"] is False

    async def test_completed_event_has_duration(self) -> None:
        pipeline = _make_pipeline()
        tool = FakeTool()
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        completed = events[-1]
        assert "duration_ms" in completed.data
        assert isinstance(completed.data["duration_ms"], int)

    async def test_prehook_deny_yields_denied(self) -> None:
        # Arrange
        hooks = ToolHookRegistry()

        async def deny_hook(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(decision=HookDecision.DENY, reason="nope")

        hooks.register_before(deny_hook)
        pipeline = _make_pipeline(hooks=hooks)
        tool = FakeTool()
        ctx = _make_ctx()

        # Act
        events = await _collect_events(pipeline, tool, {}, ctx)

        # Assert
        assert len(events) == 1
        assert events[0].type == "denied"

    async def test_doom_loop_detection(self) -> None:
        dd = MagicMock()
        dd.should_intervene = MagicMock(return_value=True)
        pipeline = _make_pipeline(doom_detector=dd)
        tool = FakeTool()
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {"cmd": "ls"}, ctx)

        assert len(events) == 1
        assert events[0].type == "doom_loop"

    async def test_doom_detector_record_called(self) -> None:
        dd = MagicMock()
        dd.should_intervene = MagicMock(return_value=False)
        dd.record = MagicMock()
        pipeline = _make_pipeline(doom_detector=dd)
        tool = FakeTool()
        ctx = _make_ctx()

        await _collect_events(pipeline, tool, {"cmd": "ls"}, ctx)
        dd.record.assert_called_once_with("test_tool", {"cmd": "ls"})

    async def test_permission_deny(self) -> None:
        # Arrange: tool has permission, and manager evaluates to DENY
        from src.infrastructure.agent.tools.executor import PermissionAction

        pm = MagicMock()
        rule = MagicMock()
        rule.action = PermissionAction.DENY
        pm.evaluate = MagicMock(return_value=rule)

        pipeline = _make_pipeline(permission_manager=pm)
        tool = FakeTool(permission="bash")
        ctx = _make_ctx()

        # Act
        events = await _collect_events(pipeline, tool, {}, ctx)

        # Assert
        assert len(events) == 1
        assert events[0].type == "denied"

    async def test_permission_ask_approved(self) -> None:
        from src.infrastructure.agent.tools.executor import PermissionAction

        pm = MagicMock()
        rule = MagicMock()
        rule.action = PermissionAction.ASK
        pm.evaluate = MagicMock(return_value=rule)
        pm.ask = AsyncMock(return_value="approve")

        pipeline = _make_pipeline(permission_manager=pm)
        tool = FakeTool(permission="bash")
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)

        # Should proceed to started + completed
        types = [e.type for e in events]
        assert "started" in types
        assert "completed" in types

    async def test_permission_ask_rejected(self) -> None:
        from src.infrastructure.agent.tools.executor import PermissionAction

        pm = MagicMock()
        rule = MagicMock()
        rule.action = PermissionAction.ASK
        pm.evaluate = MagicMock(return_value=rule)
        pm.ask = AsyncMock(return_value="reject")

        pipeline = _make_pipeline(permission_manager=pm)
        tool = FakeTool(permission="bash")
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)

        assert len(events) == 1
        assert events[0].type == "denied"

    async def test_no_permission_check_when_no_permission(self) -> None:
        pm = MagicMock()
        pipeline = _make_pipeline(permission_manager=pm)
        tool = FakeTool(permission=None)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        pm.evaluate.assert_not_called()
        assert events[-1].type == "completed"

    async def test_tool_exception_yields_error_completed(self) -> None:
        async def fail_fn(**kwargs: object) -> None:
            raise ValueError("bad input")

        pipeline = _make_pipeline()
        tool = FakeTool(_execute_fn=fail_fn)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        assert events[0].type == "started"
        assert events[1].type == "completed"
        assert events[1].data["is_error"] is True

    async def test_tool_abort_yields_aborted(self) -> None:
        async def abort_fn(**kwargs: object) -> None:
            raise ToolAbortedError("user abort")

        pipeline = _make_pipeline()
        tool = FakeTool(_execute_fn=abort_fn)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        assert events[0].type == "started"
        assert events[1].type == "aborted"

    async def test_normalize_string_result(self) -> None:
        async def str_fn(**kwargs: object) -> str:
            return "raw string"

        pipeline = _make_pipeline()
        tool = FakeTool(_execute_fn=str_fn)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        completed = events[-1]
        result = completed.data["_result"]
        assert result.output == "raw string"

    async def test_normalize_dict_with_output_key(self) -> None:
        async def dict_fn(**kwargs: object) -> dict[str, str]:
            return {"output": "hello", "extra": "data"}

        pipeline = _make_pipeline()
        tool = FakeTool(_execute_fn=dict_fn)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        result = events[-1].data["_result"]
        assert result.output == "hello"
        assert result.metadata.get("extra") == "data"

    async def test_normalize_other_json_serializable(self) -> None:
        async def list_fn(**kwargs: object) -> list[int]:
            return [1, 2, 3]

        pipeline = _make_pipeline()
        tool = FakeTool(_execute_fn=list_fn)
        ctx = _make_ctx()

        events = await _collect_events(pipeline, tool, {}, ctx)
        result = events[-1].data["_result"]
        assert result.output == "[1, 2, 3]"

    async def test_context_events_collected(self) -> None:
        async def emitting_fn(**kwargs: object) -> ToolResult:
            ctx = kwargs.get("ctx")
            if ctx:
                await ctx.emit(ToolEvent(type="custom", tool_name="test"))
            return ToolResult(output="done")

        pipeline = _make_pipeline()
        tool = FakeTool()
        ctx = _make_ctx()

        # Manually add pending events to ctx to simulate tool emitting
        ctx._pending_events.append(ToolEvent(type="task_update", tool_name="test_tool"))

        events = await _collect_events(pipeline, tool, {}, ctx)

        types = [e.type for e in events]
        assert "task_update" in types

    async def test_prehook_modifies_args(self) -> None:
        hooks = ToolHookRegistry()

        async def inject_hook(tn: str, args: dict, ctx: ToolContext) -> HookResult:
            return HookResult(args={**args, "extra": "injected"})

        hooks.register_before(inject_hook)

        received_args: dict = {}

        async def capture_fn(**kwargs: object) -> ToolResult:
            received_args.update(kwargs)
            return ToolResult(output="ok")

        pipeline = _make_pipeline(hooks=hooks)
        tool = FakeTool(_execute_fn=capture_fn)
        ctx = _make_ctx()

        await _collect_events(pipeline, tool, {"original": True}, ctx)
        assert received_args.get("extra") == "injected"
        assert received_args.get("original") is True
