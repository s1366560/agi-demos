"""Regression tests for dict event passthrough in SessionProcessor."""

from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentErrorEvent, AgentObserveEvent
from src.infrastructure.agent.processor import (
    GoalCheckResult,
    ProcessorConfig,
    SessionProcessor,
)


@pytest.mark.unit
class TestProcessorDictEvents:
    """SessionProcessor should handle dict passthrough events safely."""

    @pytest.mark.asyncio
    async def test_process_handles_dict_events_without_attribute_error(self):
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model", max_steps=3), tools=[]
        )

        async def _mock_process_step(session_id, messages):
            yield {"type": "subagent_started", "data": {"run_id": "run-1"}}

        async def _mock_goal_completion(session_id, messages):
            return GoalCheckResult(achieved=True, source="test")

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._goal_evaluator.evaluate_goal_completion = _mock_goal_completion  # type: ignore[method-assign]

        events = []
        async for event in processor.process(
            session_id="session-1",
            messages=[{"role": "user", "content": "hello"}],
        ):
            events.append(event)

        event_types = [
            event.get("type") if isinstance(event, dict) else event.event_type.value
            for event in events
        ]
        assert "subagent_started" in event_types
        assert "complete" in event_types
        assert "error" not in event_types

    @pytest.mark.asyncio
    async def test_process_stops_on_dict_error_event(self):
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model", max_steps=3), tools=[]
        )

        async def _mock_process_step(session_id, messages):
            yield {"type": "error", "data": {"message": "tool failed"}}

        processor._process_step = _mock_process_step  # type: ignore[method-assign]

        events = []
        async for event in processor.process(
            session_id="session-1",
            messages=[{"role": "user", "content": "hello"}],
        ):
            events.append(event)

        event_types = [
            event.get("type") if isinstance(event, dict) else event.event_type.value
            for event in events
        ]
        assert event_types == ["start", "error"]

    @pytest.mark.asyncio
    async def test_process_stops_consuming_step_after_terminal_workspace_contract(self):
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model", max_steps=3), tools=[]
        )

        async def _mock_process_step(session_id, messages):
            yield AgentObserveEvent(
                tool_name="workspace_submit_worktree_preparation",
                result={"worktree_preparation": {"status": "prepared"}},
            )
            yield AgentErrorEvent(
                message="Workspace contract-agent session ended without calling submit tool.",
                code="WORKSPACE_CONTRACT_TOOL_REQUIRED",
            )

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._goal_evaluator.evaluate_task_completion_gate = AsyncMock(  # type: ignore[method-assign]
            return_value=None
        )

        events = []
        async for event in processor.process(
            session_id="session-1",
            messages=[{"role": "user", "content": "hello"}],
        ):
            events.append(event)

        event_types = [
            event.get("type") if isinstance(event, dict) else event.event_type.value
            for event in events
        ]
        assert event_types == [
            "start",
            "observe",
            "status",
            "complete",
        ]
        assert not any(
            isinstance(event, AgentErrorEvent)
            and event.code == "WORKSPACE_CONTRACT_TOOL_REQUIRED"
            for event in events
        )
