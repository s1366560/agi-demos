"""Losing pause authority is a fatal transport error, never an implicit user Stop."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentCompleteEvent, AgentErrorEvent, AgentObserveEvent
from src.infrastructure.agent.core.llm_stream import StreamEventType
from src.infrastructure.agent.core.message import ToolState
from src.infrastructure.agent.native_computer_use.store import DeviceBridgeError
from src.infrastructure.agent.processor.native_control import (
    NativeControlWaitError,
    await_native_control,
)
from src.infrastructure.agent.processor.processor import ToolDefinition
from src.infrastructure.agent.tools.result import ToolControlOutcome, ToolResult
from src.tests.unit.infrastructure.agent.processor.test_native_control_results import (
    control_result,
    processor_for,
)

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("pipeline", [False, True])
async def test_lost_pause_authority_ends_run_before_model_or_task_updates(pipeline):
    paused = control_result(ToolControlOutcome.USER_PAUSED)
    waiting, disconnected = asyncio.Event(), asyncio.Event()

    async def wait():
        waiting.set()
        await disconnected.wait()
        raise DeviceBridgeError("computer_use_control_cancelled")

    paused.control_wait = wait
    processor, part, definition = processor_for(paused, pipeline)
    processor._abort_event = asyncio.Event()
    next_model_or_task_update = AsyncMock()
    processor._evaluate_goal_progress = AsyncMock()

    async def step(_session_id, _messages):
        async for event in processor._execute_tool("session", "call", definition.name, {}):
            yield event
        await next_model_or_task_update()

    processor._process_step = step
    events = []

    async def run():
        async for event in processor._run_native_loop("session", []):
            events.append(event)

    running = asyncio.create_task(run())
    try:
        await asyncio.wait_for(waiting.wait(), 1)
        assert not running.done()
        assert part.status == ToolState.CANCELLED
        disconnected.set()
        await asyncio.wait_for(running, 1)
    finally:
        if not running.done():
            running.cancel()
            await asyncio.gather(running, return_exceptions=True)

    assert part.status == ToolState.ERROR
    observations = [event for event in events if isinstance(event, AgentObserveEvent)]
    assert len(observations) == 2
    assert observations[0].control_outcome == "user_paused" and not observations[0].error
    assert observations[1].status == "error" and observations[1].error
    assert observations[1].control_outcome == "user_paused"
    assert any(
        isinstance(event, AgentErrorEvent) and event.code == "NativeControlWaitError"
        for event in events
    )
    assert not any(isinstance(event, AgentCompleteEvent) for event in events)
    assert not processor._native_control_stopped
    assert processor._goal_evaluator._native_control_outcome is None
    assert processor._session_instructions == []
    processor._evaluate_goal_progress.assert_not_awaited()
    next_model_or_task_update.assert_not_awaited()
    definition.execute.assert_awaited_once()


async def test_missing_pause_waiter_is_fatal_without_inventing_resume():
    paused = control_result(ToolControlOutcome.USER_PAUSED)
    with pytest.raises(NativeControlWaitError):
        await await_native_control(paused, None)


async def test_pause_waiter_setup_failure_is_fatal_without_inventing_resume():
    paused = control_result(ToolControlOutcome.USER_PAUSED)

    def unavailable():
        raise DeviceBridgeError("computer_use_control_cancelled")

    paused.control_wait = unavailable
    with pytest.raises(NativeControlWaitError) as raised:
        await await_native_control(paused, None)
    assert isinstance(raised.value.cause, DeviceBridgeError)


@pytest.mark.parametrize("pipeline", [False, True])
async def test_parallel_failure_preserves_all_finished_observations_then_ends_run(
    monkeypatch, pipeline
):
    paused = control_result(ToolControlOutcome.USER_PAUSED)
    paused.control_wait = AsyncMock(side_effect=DeviceBridgeError("computer_use_control_cancelled"))
    processor, _part, definition = processor_for(paused, pipeline)
    independent = ToolDefinition(
        name="independent_read",
        description="Independent authorized read",
        parameters={},
        execute=AsyncMock(return_value=ToolResult(output="independent result")),
    )
    processor.tools[independent.name] = independent
    processor.config.enable_parallel_tool_execution = True
    processor._abort_event = asyncio.Event()
    processor._evaluate_goal_progress = AsyncMock()
    model_calls = []

    async def generate(_self, _messages, **_kwargs):
        model_calls.append(True)
        for call_id, tool in (("native-call", definition), ("other-call", independent)):
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_START, data={"call_id": call_id, "name": tool.name}
            )
            yield SimpleNamespace(
                type=StreamEventType.TOOL_CALL_END,
                data={"call_id": call_id, "name": tool.name, "arguments": {}},
            )
        yield SimpleNamespace(type=StreamEventType.FINISH, data={"reason": "tool_calls"})

    monkeypatch.setattr("src.infrastructure.agent.processor.processor.LLMStream.generate", generate)
    events = [event async for event in processor._run_native_loop("session", [])]
    observations = [event for event in events if isinstance(event, AgentObserveEvent)]
    assert [(event.call_id, event.status) for event in observations] == [
        ("native-call", "cancelled"),
        ("native-call", "error"),
        ("other-call", "completed"),
    ]
    assert any(
        isinstance(event, AgentErrorEvent) and event.code == "NativeControlWaitError"
        for event in events
    )
    assert not any(isinstance(event, AgentCompleteEvent) for event in events)
    assert model_calls == [True]
    processor._evaluate_goal_progress.assert_not_awaited()
    definition.execute.assert_awaited_once()
    independent.execute.assert_awaited_once()
