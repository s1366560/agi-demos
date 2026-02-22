"""Regression tests for dict event passthrough in SessionProcessor."""

import pytest

from src.infrastructure.agent.processor.processor import (
    GoalCheckResult,
    ProcessorConfig,
    SessionProcessor,
)


@pytest.mark.unit
class TestProcessorDictEvents:
    """SessionProcessor should handle dict passthrough events safely."""

    @pytest.mark.asyncio
    async def test_process_handles_dict_events_without_attribute_error(self):
        processor = SessionProcessor(config=ProcessorConfig(model="test-model", max_steps=3), tools=[])

        async def _mock_process_step(session_id, messages):
            yield {"type": "subagent_run_started", "data": {"run_id": "run-1"}}

        async def _mock_goal_completion(session_id, messages):
            return GoalCheckResult(achieved=True, source="test")

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._evaluate_goal_completion = _mock_goal_completion  # type: ignore[method-assign]

        events = []
        async for event in processor.process(
            session_id="session-1",
            messages=[{"role": "user", "content": "hello"}],
        ):
            events.append(event)

        event_types = [
            event.get("type") if isinstance(event, dict) else event.event_type.value for event in events
        ]
        assert "subagent_run_started" in event_types
        assert "complete" in event_types
        assert "error" not in event_types

    @pytest.mark.asyncio
    async def test_process_stops_on_dict_error_event(self):
        processor = SessionProcessor(config=ProcessorConfig(model="test-model", max_steps=3), tools=[])

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
            event.get("type") if isinstance(event, dict) else event.event_type.value for event in events
        ]
        assert event_types == ["start", "error"]
