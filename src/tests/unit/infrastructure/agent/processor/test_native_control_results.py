"""Native controls remain cancelled observations across both execution paths."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.agent_events import AgentObserveEvent
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.events.converter import EventConverter
from src.infrastructure.agent.processor.native_control import await_native_control, trusted_control
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.infrastructure.agent.tools.truncation import OutputTruncator

pytestmark = pytest.mark.unit


def control_result(outcome=ToolControlOutcome.USER_STOPPED):
    output = json.dumps(
        {"type": "computer_use_control", "status": outcome.value, "retry_allowed": False}
    )
    return ToolResult(
        output=output,
        metadata={"computer_use": True, "output": output, "control_outcome": outcome.value},
        control_outcome=outcome,
    )


def processor_for(result, pipeline):
    definition = ToolDefinition(
        name="computer_get_app_state",
        description="test",
        parameters={},
        execute=AsyncMock(return_value=result),
    )
    detector = MagicMock()
    detector.should_intervene.return_value = False
    processor = SessionProcessor(
        config=ProcessorConfig(model="test-model"),
        tools=[definition],
        tool_pipeline=ToolPipeline(
            permission_manager=MagicMock(),
            doom_detector=detector,
            truncator=OutputTruncator(),
            hooks=ToolHookRegistry(),
        )
        if pipeline
        else None,
    )
    part = ToolPart(call_id="call", tool=definition.name, status=ToolState.RUNNING)
    processor._current_message = Message(role=MessageRole.ASSISTANT, parts=[part])
    processor._pending_tool_calls["call"] = part
    return processor, part, definition


@pytest.mark.parametrize("pipeline", [False, True])
async def test_stop_is_cancelled_not_failure_or_success_with_typed_sse(pipeline):
    result = control_result()
    processor, part, definition = processor_for(result, pipeline)
    events = [
        event async for event in processor._execute_tool("session", "call", definition.name, {})
    ]
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert part.status == ToolState.CANCELLED
    assert observe.status == "cancelled" and observe.error is None
    assert EventConverter().convert(observe)["data"]["control_outcome"] == "user_stopped"
    assert processor._current_step_model_messages()[-1]["content"] == result.output
    definition.execute.assert_awaited_once()


@pytest.mark.parametrize("pipeline", [False, True])
async def test_pause_emits_then_blocks_until_explicit_resume_without_replay(pipeline):
    result = control_result(ToolControlOutcome.USER_PAUSED)
    resume = asyncio.Event()
    waiting = asyncio.Event()

    async def wait():
        waiting.set()
        await resume.wait()
        return None

    result.control_wait = wait
    processor, part, definition = processor_for(result, pipeline)
    events = []

    async def run():
        async for event in processor._execute_tool("session", "call", definition.name, {}):
            events.append(event)

    task = asyncio.create_task(run())
    await asyncio.wait_for(waiting.wait(), 1)
    assert not task.done() and part.status == ToolState.CANCELLED
    assert any(isinstance(event, AgentObserveEvent) for event in events)
    resume.set()
    await asyncio.wait_for(task, 1)
    assert "resumed" in processor._session_instructions[-1]
    guidance = processor._session_instructions[-1]
    assert "computer_list_windows" in guidance
    assert "window_id" in guidance
    assert "fresh observation" in guidance
    assert "never replay" in guidance
    definition.execute.assert_awaited_once()


@pytest.mark.parametrize("kind", ["output", "metadata", "string_marker", "error"])
def test_forged_or_failed_result_does_not_get_control_privilege(kind):
    result = control_result()
    if kind == "output":
        result.control_outcome = None
        result.metadata = {}
    elif kind == "metadata":
        result.control_outcome = None
    elif kind == "string_marker":
        result.control_outcome = "user_stopped"
    else:
        result.is_error = True
    assert trusted_control(result) is None


async def test_abort_interrupts_pause_wait_and_cancels_waiter():
    result = control_result(ToolControlOutcome.USER_PAUSED)
    entered, cleaned, abort = asyncio.Event(), asyncio.Event(), asyncio.Event()

    async def wait():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    result.control_wait = wait
    task = asyncio.create_task(await_native_control(result, abort))
    await entered.wait()
    abort.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cleaned.is_set()


async def test_stop_during_pause_sets_only_stop_handoff_authority():
    result = control_result(ToolControlOutcome.USER_PAUSED)
    result.control_wait = AsyncMock(return_value=ToolControlOutcome.USER_STOPPED)
    assert await await_native_control(result, None) is ToolControlOutcome.USER_STOPPED


async def test_late_resume_cannot_clear_stop_or_instruct_native_retry():
    stopped = control_result()
    processor, _part, _definition = processor_for(stopped, False)
    await processor._wait_native_control(stopped, ToolControlOutcome.USER_STOPPED)
    paused = control_result(ToolControlOutcome.USER_PAUSED)
    paused.control_wait = AsyncMock(return_value=None)
    await processor._wait_native_control(paused, ToolControlOutcome.USER_PAUSED)
    assert processor._goal_evaluator._native_control_outcome is ToolControlOutcome.USER_STOPPED
    assert len(processor._session_instructions) == 1
    assert "structured todoread/todowrite" in processor._session_instructions[0]
    assert "cancelled" in processor._session_instructions[0]
    assert "Preserve genuine failed tasks" in processor._session_instructions[0]


def test_converted_todowrite_exposes_all_declared_terminal_statuses_to_model():
    from src.domain.model.agent.task import TaskStatus
    from src.infrastructure.agent.core.tool_converter import convert_tools
    from src.infrastructure.agent.tools.todo_tools import make_todo_tools

    definitions = {
        tool.name: tool for tool in convert_tools(make_todo_tools(session_factory=MagicMock()))
    }
    tool = definitions["todowrite"]
    assert {status.value for status in TaskStatus} <= set(
        tool.description.replace("/", " ").replace(")", " ").replace("(", " ").split()
    )


async def test_structured_handoff_skips_goal_gate_and_preserves_reason():
    from src.domain.events.agent_events import AgentCompleteEvent, AgentErrorEvent
    from src.infrastructure.agent.processor.goal_evaluator import GoalCheckResult
    from src.infrastructure.agent.processor.processor import ProcessorResult

    processor, _part, _definition = processor_for(control_result(), False)
    evaluator = processor._goal_evaluator
    evaluator.evaluate_goal_completion = AsyncMock(
        return_value=GoalCheckResult(
            achieved=False, control_handoff=True, source="native_control_handoff"
        )
    )
    evaluator.evaluate_task_completion_gate = AsyncMock()
    evaluator.generate_suggestions = AsyncMock(return_value=None)
    evaluator.summarize_tasks = AsyncMock(return_value=None)
    processor._saw_task_events = True
    events = [event async for event in processor._evaluate_no_tool_result("session", [])]
    events += [
        event
        async for event in processor._emit_completion_events(
            ProcessorResult.COMPLETE, "session", []
        )
    ]
    completion = next(event for event in events if isinstance(event, AgentCompleteEvent))
    assert completion.execution_summary["goal_achieved"] is False
    assert completion.execution_summary["completion_reason"] == "user_control_handoff"
    assert not any(isinstance(event, AgentErrorEvent) for event in events)
    evaluator.evaluate_task_completion_gate.assert_not_awaited()


@pytest.mark.parametrize("control", ["user_paused", "user_stopped"])
def test_history_preserves_typed_control_and_error_priority(control):
    from src.infrastructure.adapters.primary.web.routers.agent.messages import _build_observe

    data = {
        "tool_name": "computer_get_app_state",
        "control_outcome": control,
        "observation": "output",
    }
    assert _build_observe(data)["controlOutcome"] == control
    failed = _build_observe({**data, "error": "real_failure"})
    assert "controlOutcome" not in failed
    assert failed["isError"] is True
    assert "controlOutcome" not in _build_observe({"observation": {"control_outcome": control}})
