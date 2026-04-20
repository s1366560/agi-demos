"""Tests for final completion gating in SessionProcessor."""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.processor import (
    GoalCheckResult,
    ProcessorConfig,
    SessionProcessor,
)


@pytest.mark.unit
class TestProcessorCompletionGate:
    """Final COMPLETE must still pass the persisted task gate."""

    @pytest.mark.asyncio
    async def test_process_blocks_complete_when_final_task_gate_fails(self) -> None:
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model", max_steps=3),
            tools=[],
        )

        async def _mock_process_step(session_id, messages):
            if False:
                yield {"type": "noop", "data": {}}

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._goal_evaluator.evaluate_goal_completion = AsyncMock(  # type: ignore[method-assign]
            return_value=GoalCheckResult(achieved=True, source="llm_self_check")
        )
        processor._goal_evaluator.evaluate_task_completion_gate = AsyncMock(  # type: ignore[method-assign]
            return_value=GoalCheckResult(
                achieved=False,
                reason="1 task(s) still in progress",
                source="tasks",
                pending_tasks=1,
            )
        )
        processor._goal_evaluator.generate_suggestions = AsyncMock(return_value=None)  # type: ignore[method-assign]
        processor._notify_plugin_hook = AsyncMock(return_value={})  # type: ignore[method-assign]

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
        status_values = [getattr(event, "status", None) for event in events]

        assert "complete" not in event_types
        assert "error" in event_types
        assert "goal_pending:tasks" in status_values
        assert not any(
            isinstance(status, str) and status.startswith("goal_achieved:")
            for status in status_values
        )
        processor._notify_plugin_hook.assert_any_await(  # type: ignore[attr-defined]
            "on_session_end",
            {
                "session_id": "session-1",
                "step_count": 1,
                "tenant_id": None,
                "project_id": None,
                "result": "STOP",
            },
        )

    @pytest.mark.asyncio
    async def test_process_blocks_complete_when_task_events_seen_without_todoread(self) -> None:
        processor = SessionProcessor(
            config=ProcessorConfig(model="test-model", max_steps=3),
            tools=[],
        )

        async def _mock_process_step(session_id, messages):
            yield {"type": "task_list_updated", "data": {"tasks": [{"id": "t1", "status": "pending"}]}}

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._goal_evaluator.evaluate_goal_completion = AsyncMock(  # type: ignore[method-assign]
            return_value=GoalCheckResult(achieved=True, source="llm_self_check")
        )
        processor._goal_evaluator.generate_suggestions = AsyncMock(return_value=None)  # type: ignore[method-assign]
        processor._notify_plugin_hook = AsyncMock(return_value={})  # type: ignore[method-assign]

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
        status_values = [getattr(event, "status", None) for event in events]

        assert "complete" not in event_types
        assert "error" in event_types
        assert "goal_pending:tasks" in status_values
        assert not any(
            isinstance(status, str) and status.startswith("goal_achieved:")
            for status in status_values
        )
