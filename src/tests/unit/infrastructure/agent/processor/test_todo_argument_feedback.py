"""Malformed task updates fail before authority; native Stop retains progress authority."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import AgentObserveEvent
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.core.tool_converter import convert_tools
from src.infrastructure.agent.events.converter import EventConverter
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.hooks import HookResult, ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.infrastructure.agent.tools.todo_tools import todowrite_tool
from src.infrastructure.agent.tools.truncation import OutputTruncator
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


def test_minimax_actual_request_keeps_update_schema_and_full_description():
    from litellm.llms.minimax.chat.transformation import MinimaxChatConfig

    wire = convert_tools({"todowrite": todowrite_tool})[0].to_openai_format()
    request = MinimaxChatConfig().transform_request(
        model="MiniMax-M3",
        messages=[{"role": "user", "content": "Update task progress"}],
        optional_params={"tools": [wire]},
        litellm_params={},
        headers={},
    )
    actual = request["tools"][0]["function"]
    assert actual["parameters"] == todowrite_tool.parameters
    assert actual["description"] == todowrite_tool.description
    assert actual["parameters"]["allOf"]
    assert "todo_id" in actual["description"] and "cancelled" in actual["description"]


def make_processor(*, pipeline: bool, hooks: ToolHookRegistry | None = None):
    execute = AsyncMock(return_value=ToolResult(output='{"success":true}'))
    definition = convert_tools({"todowrite": replace(todowrite_tool, execute=execute)})[0]
    manager = MagicMock()
    manager.evaluate.return_value.action = "allow"
    detector = MagicMock()
    detector.should_intervene.return_value = False
    processor = SessionProcessor(
        config=ProcessorConfig(
            model="minimax/MiniMax-M3", approved_run_required=True, run_id="run"
        ),
        tools=[definition],
        tool_pipeline=ToolPipeline(
            manager, detector, OutputTruncator(), hooks or ToolHookRegistry()
        )
        if pipeline
        else None,
    )
    processor._abort_event = asyncio.Event()
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[])
    return processor, execute, manager


async def dispatch(processor, call_id, tool_name, arguments):
    part = ToolPart(
        call_id=call_id, tool=tool_name, input=deepcopy(arguments), status=ToolState.RUNNING
    )
    processor._pending_tool_calls[call_id] = part
    processor._current_message.parts.append(part)
    events = [
        event
        async for event in processor._execute_tool("conversation", call_id, tool_name, arguments)
    ]
    return part, events


def read_only_guard(monkeypatch):
    permissions = []

    async def require(permission, **_kwargs):
        permissions.append(permission)
        if permission not in {"conversation_progress", "computer_observe"}:
            raise RuntimeV2Error(
                "run_tool_permission_denied", "Approved run does not authorize this tool operation"
            )

    monkeypatch.setattr(
        "src.application.services.approved_run_tool_permission_v2.require_approved_run_tool_permission_v2",
        require,
    )
    return permissions


async def test_direct_pipeline_rejects_invalid_declared_arguments_before_permission(monkeypatch):
    processor, execute, manager = make_processor(pipeline=True)
    permissions = read_only_guard(monkeypatch)
    tool = replace(todowrite_tool, execute=execute)
    ctx = ToolContext(
        session_id="session",
        message_id="message",
        call_id="call",
        agent_name="agent",
        conversation_id="conversation",
        abort_signal=asyncio.Event(),
    )
    events = [
        event
        async for event in processor._tool_pipeline.execute(
            tool, {"action": "update", "todos": [{"status": "cancelled"}]}, ctx
        )
    ]
    assert len(events) == 1 and events[0].type == "completed"
    result = events[0].data["_result"]
    assert result.is_error
    error = json.loads(result.output)
    assert error["error"] == "invalid_tool_arguments" and "todo_id" in error["message"]
    assert permissions == []
    execute.assert_not_awaited()
    manager.evaluate.assert_not_called()


@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize(
    "arguments",
    [
        {"action": "update", "todos": [{"status": "cancelled"}, {"id": "task-one"}]},
        {"action": "update", "todos": [{"status": "cancelled"}, {"$text": "task-one"}]},
        {
            "action": "update",
            "todo_id": "task-one",
            "todos": [{"status": "cancelled"}, {"status": "completed"}],
        },
    ],
)
async def test_malformed_update_reaches_model_as_argument_error_before_permission(
    monkeypatch, pipeline, arguments
):
    processor, execute, manager = make_processor(pipeline=pipeline)
    permissions = read_only_guard(monkeypatch)
    part, events = await dispatch(processor, "call", "todowrite", arguments)
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert part.status == ToolState.ERROR and observe.error
    assert "does not authorize" not in observe.error
    assert any(field in observe.error for field in ("todo_id", "todos", "$text", "too long"))
    assert EventConverter().convert(observe)["data"]["error"] == part.error
    assert processor._current_step_model_messages()[-1]["content"] == f"Error: {part.error}"
    assert permissions == []
    execute.assert_not_awaited()
    manager.evaluate.assert_not_called()
    assert not processor._abort_event.is_set()


@pytest.mark.parametrize("pipeline", [False, True])
async def test_native_stop_retains_read_only_task_progress_and_real_denials(monkeypatch, pipeline):
    processor, execute, _manager = make_processor(pipeline=pipeline)
    permissions = read_only_guard(monkeypatch)
    outcome = ToolControlOutcome.USER_STOPPED
    stop = ToolResult(
        output=json.dumps(
            {"type": "computer_use_control", "status": outcome.value, "retry_allowed": False}
        ),
        control_outcome=outcome,
    )
    processor.tools["computer_get_app_state"] = ToolDefinition(
        name="computer_get_app_state",
        description="Native observation",
        parameters={},
        permission="computer_observe",
        execute=AsyncMock(return_value=stop),
    )
    stopped, events = await dispatch(processor, "stop", "computer_get_app_state", {})
    assert stopped.status == ToolState.CANCELLED
    assert not processor._abort_event.is_set()
    assert any(
        isinstance(event, AgentObserveEvent) and event.control_outcome == "user_stopped"
        for event in events
    )
    progress = {"action": "update", "todo_id": "task-one", "todos": [{"status": "cancelled"}]}
    part, _events = await dispatch(processor, "progress", "todowrite", progress)
    assert part.status == ToolState.COMPLETED and not part.error
    assert "conversation_progress" in permissions
    execute.assert_awaited_once()
    assert execute.call_args.kwargs == progress
    denied, _events = await dispatch(
        processor,
        "structural",
        "todowrite",
        {
            "action": "update",
            "todo_id": "task-one",
            "todos": [{"content": "Expand scope after stop"}],
        },
    )
    assert denied.status == ToolState.ERROR and "does not authorize" in denied.error
    assert execute.await_count == 1
    assert not processor._abort_event.is_set()


@pytest.mark.parametrize("invalid", [True, False])
async def test_hook_arguments_are_validated_before_recomputing_permissions(monkeypatch, invalid):
    hooks = ToolHookRegistry()

    async def change(_name, _args, _ctx):
        return HookResult(
            args={
                "action": "update",
                "todo_id": "task-one",
                "todos": [{"$text": "cancelled"} if invalid else {"content": "Changed scope"}],
            }
        )

    hooks.register_before(change)
    processor, execute, manager = make_processor(pipeline=True, hooks=hooks)
    permissions = read_only_guard(monkeypatch)
    part, events = await dispatch(
        processor,
        "call",
        "todowrite",
        {
            "action": "update",
            "todo_id": "task-one",
            "todos": [{"status": "cancelled"}],
        },
    )
    assert part.status == ToolState.ERROR
    execute.assert_not_awaited()
    if invalid:
        result = json.loads(part.error)
        assert result["error"] == "invalid_tool_arguments"
        assert "$text" in result["message"]
        assert "workspace_task_write" not in permissions
        manager.evaluate.assert_not_called()
        assert any(
            isinstance(event, AgentObserveEvent) and event.error == part.error for event in events
        )
    else:
        assert "workspace_task_write" in permissions
        assert "does not authorize" in part.error
