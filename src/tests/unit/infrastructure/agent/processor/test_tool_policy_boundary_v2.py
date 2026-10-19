"""The production tool path applies generation policy before authorization/output."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.events.agent_events import AgentObserveEvent
from src.infrastructure.agent.core.message import ToolPart, ToolState
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.plugins.v2.agent_runtime_dispatcher import AgentRuntimeDispatchResultV2


class _Dispatcher:
    def __init__(self, *, before=None, after=None):
        self.before = before
        self.after = after
        self.seen = []

    async def dispatch(self, name, payload=None):
        value = deepcopy(payload or {})
        self.seen.append((name, value))
        transform = (
            self.before
            if name == "before_tool_execution"
            else (self.after if name == "transform_tool_result" else None)
        )
        if transform:
            value = transform(value)
        return AgentRuntimeDispatchResultV2(payload=value)


def _processor(dispatcher, execute):
    tool = ToolDefinition(
        name="write",
        description="Write a file",
        execute=execute,
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
            "additionalProperties": False,
        },
        permission="file_write",
    )
    processor = SessionProcessor(
        config=ProcessorConfig(model="test", plugin_event_dispatcher=dispatcher),
        tools=[tool],
    )
    processor._pending_tool_calls["call"] = ToolPart(
        call_id="call",
        tool="write",
        status=ToolState.PENDING,
    )
    processor._abort_event = asyncio.Event()
    return processor


async def _execute(processor):
    return [
        event
        async for event in processor._execute_tool(
            "session",
            "call",
            "write",
            {"path": "original"},
        )
    ]


@pytest.mark.unit
async def test_rewritten_arguments_are_checked_before_chat_authority_and_invocation():
    dispatcher = _Dispatcher(before=lambda payload: {**payload, "arguments": {"path": "changed"}})
    execute = AsyncMock(return_value="ok")
    processor = _processor(dispatcher, execute)
    seen = []

    async def authority(permission, tool_name, arguments, **kwargs):
        seen.append(deepcopy(arguments))
        return "allow"

    with patch(
        "src.application.services.chat_run_tool_permission_v2.decision_for_current_chat_tool_v2",
        side_effect=authority,
    ):
        await _execute(processor)
    assert seen and all(args == {"path": "changed"} for args in seen)
    execute.assert_awaited_once_with(path="changed")
    assert processor._pending_tool_calls["call"].input == {"path": "changed"}
    assert [name for name, _ in dispatcher.seen].count("before_tool_execution") == 1


@pytest.mark.unit
async def test_policy_cannot_send_invalid_arguments_to_tool():
    dispatcher = _Dispatcher(before=lambda payload: {**payload, "arguments": {"path": 7}})
    execute = AsyncMock(return_value="ok")
    events = await _execute(_processor(dispatcher, execute))
    execute.assert_not_awaited()
    assert isinstance(events[-1], AgentObserveEvent)
    assert events[-1].error


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["deny", "cancel"])
async def test_policy_stop_never_invokes_tool(kind):
    dispatcher = _Dispatcher(before=lambda payload: {**payload, "decision": {"kind": kind}})
    execute = AsyncMock(return_value="ok")
    processor = _processor(dispatcher, execute)
    events = await _execute(processor)
    execute.assert_not_awaited()
    assert events[-1].error
    assert processor._abort_event.is_set() is (kind == "cancel")


@pytest.mark.unit
async def test_policy_ask_uses_reviewed_arguments_and_rejection_stops_execution():
    dispatcher = _Dispatcher(
        before=lambda payload: {
            **payload,
            "arguments": {"path": "reviewed"},
            "decision": {"kind": "ask"},
        }
    )
    execute = AsyncMock(return_value="ok")
    processor = _processor(dispatcher, execute)
    reviewed = []

    async def ask(session, call, name, arguments, part, definition):
        reviewed.append(arguments)
        part.status = ToolState.ERROR
        if False:
            yield None

    processor._ask_tool_permission = ask
    await _execute(processor)
    execute.assert_not_awaited()
    assert reviewed == [{"path": "reviewed"}]


@pytest.mark.unit
@pytest.mark.parametrize("raises", [False, True])
async def test_post_policy_runs_before_observe_model_output_and_notification(raises):
    dispatcher = _Dispatcher(
        after=lambda payload: {
            **payload,
            "result": {"output": "sanitized", "is_error": False, "metadata": {}},
        }
    )
    execute = AsyncMock(
        side_effect=ValueError("raw private failure") if raises else None,
        return_value=ToolResult(output="raw private output"),
    )
    processor = _processor(dispatcher, execute)
    events = await _execute(processor)
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert observe.result == "sanitized"
    assert observe.error is None
    assert processor._pending_tool_calls["call"].output == "sanitized"
    notification = next(value for name, value in dispatcher.seen if name == "after_tool_execution")
    assert notification["result"] == "sanitized"


@pytest.mark.unit
async def test_blocked_result_clears_pending_side_effects():
    dispatcher = _Dispatcher(
        after=lambda payload: {
            **payload,
            "decision": {"kind": "block", "reason": "result withheld"},
        }
    )
    processor = _processor(dispatcher, AsyncMock(return_value="raw output"))
    events = await _execute(processor)
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert observe.result == "result withheld"
    assert observe.error == "result withheld"
    assert processor._last_output_str == "result withheld"


@pytest.mark.unit
async def test_command_tool_path_uses_same_before_and_after_policy():
    from src.infrastructure.agent.commands.types import ToolCallResult

    dispatcher = _Dispatcher(
        before=lambda value: {**value, "arguments": {"path": "changed"}},
        after=lambda value: {
            **value,
            "result": {"output": "accepted", "is_error": False, "metadata": {}},
        },
    )
    execute = AsyncMock(return_value="private raw")
    processor = _processor(dispatcher, execute)
    events = [
        event
        async for event in processor._emit_command_result(
            ToolCallResult(tool_name="write", args={"path": "original"})
        )
    ]
    execute.assert_awaited_once_with(path="changed")
    assert next(e for e in events if isinstance(e, AgentObserveEvent)).result == "accepted"


@pytest.mark.unit
@pytest.mark.parametrize("kind", ["deny", "ask", "cancel"])
async def test_internal_artifact_tools_cannot_bypass_generation_policy(kind):
    execute = AsyncMock(return_value="private raw")
    processor = _processor(
        _Dispatcher(before=lambda value: {**value, "decision": {"kind": kind}}), execute
    )
    assert (
        await processor._execute_internal_tool_for_artifact("write", {"path": "original"}) is None
    )
    execute.assert_not_awaited()


@pytest.mark.unit
async def test_internal_artifact_tool_result_is_transformed_before_use():
    dispatcher = _Dispatcher(
        after=lambda value: {
            **value,
            "result": {"output": "accepted", "is_error": False, "metadata": {}},
        }
    )
    execute = AsyncMock(return_value="private raw")
    processor = _processor(dispatcher, execute)
    processor._langfuse_context = {"conversation_id": "session"}
    assert (
        await processor._execute_internal_tool_for_artifact(
            "write", {"path": "original"}
        )
        == "accepted"
    )
    assert all(payload["session_id"] == "session" for _, payload in dispatcher.seen)


@pytest.mark.unit
@pytest.mark.parametrize("block", [False, True])
async def test_pipeline_raw_side_events_wait_for_policy_and_are_not_published_when_replaced(block):
    from src.infrastructure.agent.tools.result import ToolEvent

    class Pipeline:
        async def execute(self, tool, args, ctx):
            await tool.execute(**args)
            yield ToolEvent(
                type="legacy_event",
                tool_name=tool.name,
                data={"event": {"type": "mcp_app_result", "data": {"private": True}}},
            )
            yield ToolEvent.completed(tool.name, ToolResult(output="private raw"))

    def transform(value):
        return {
            **value,
            "decision": {"kind": "block" if block else "accept"},
            "result": {"output": "accepted", "is_error": False, "metadata": {}},
        }

    processor = _processor(_Dispatcher(after=transform), AsyncMock(return_value="private raw"))
    processor._tool_pipeline = Pipeline()
    events = await _execute(processor)
    assert not any(
        isinstance(event, dict) and event.get("type") == "mcp_app_result" for event in events
    )
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert "private" not in str(observe.result)


@pytest.mark.unit
async def test_result_policy_failure_is_closed_and_does_not_publish_raw_output():
    def fail(value):
        raise ValueError("private raw schema details")

    processor = _processor(_Dispatcher(after=fail), AsyncMock(return_value="private raw"))
    events = await _execute(processor)
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert "private" not in str(observe.result)
    assert observe.error == "Tool result withheld because policy validation failed"
