"""Explicit tool failures must survive both processor execution paths."""

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.domain.events.agent_events import AgentObserveEvent
from src.infrastructure.agent.core.message import Message, MessageRole, ToolPart, ToolState
from src.infrastructure.agent.events.converter import EventConverter
from src.infrastructure.agent.processor.processor import (
    ProcessorConfig,
    SessionProcessor,
    ToolDefinition,
)
from src.infrastructure.agent.tools.define import ToolInfo
from src.infrastructure.agent.tools.hooks import ToolHookRegistry
from src.infrastructure.agent.tools.pipeline import ToolPipeline
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.truncation import OutputTruncator


@pytest.mark.unit
@pytest.mark.parametrize("pipeline", [False, True])
@pytest.mark.parametrize("failed", [False, True])
async def test_result_status_reaches_event_and_next_model_step(
    pipeline: bool, failed: bool
) -> None:
    async def execute(**_kwargs: Any) -> ToolResult:
        return ToolResult(output="Task not found" if failed else "Updated", is_error=failed)

    definition = ToolDefinition(
        name="test_result", description="test", parameters={}, execute=execute
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
    processor.doom_loop_detector.record_error("earlier_tool", "Earlier failure")
    stream = processor._execute_tool("session", "call", definition.name, {})
    events = [event async for event in stream]
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    expected_status = ToolState.ERROR if failed else ToolState.COMPLETED
    assert part.status == expected_status
    assert observe.status == expected_status.value
    assert observe.error == part.error == ("Task not found" if failed else None)
    assert part.output == ("Task not found" if failed else "Updated")
    assert processor.doom_loop_detector.consecutive_error_count == (1 if failed else 0)
    wire = EventConverter().convert(observe)
    assert wire["data"]["status"] == expected_status.value
    assert wire["data"].get("error") == part.error
    assert processor._current_step_model_messages()[-1]["content"] == (
        "Error: Task not found" if failed else "Updated"
    )


@pytest.mark.unit
async def test_pipeline_toolinfo_exception_is_an_error_observation() -> None:
    async def execute(_context: Any, **_kwargs: Any) -> ToolResult:
        raise ValueError("Task not found")

    definition = ToolDefinition(
        name="test_result", description="test", parameters={}, execute=execute
    )
    definition._tool_instance = ToolInfo(
        name=definition.name, description="test", parameters={}, execute=execute
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
        ),
    )
    part = ToolPart(call_id="call", tool=definition.name, status=ToolState.RUNNING)
    events = [
        event
        async for event in processor._execute_tool_via_pipeline(
            "session",
            "call",
            definition.name,
            {},
            part,
            definition,
        )
    ]
    observe = next(event for event in events if isinstance(event, AgentObserveEvent))
    assert part.status == ToolState.ERROR
    assert observe.error == "Task not found"
    assert observe.status == "error"
