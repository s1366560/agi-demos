"""Optional suggestions must not hold a completed run open."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.processor import (
    ProcessorConfig,
    ProcessorResult,
    ProcessorState,
    SessionProcessor,
    goal_evaluator,
)
from src.infrastructure.agent.processor.goal_evaluator import GoalEvaluator
from src.infrastructure.plugins.v2.agent_loop import BuiltinAgentLoopResolverV2


@pytest.mark.unit
async def test_stalled_suggestions_are_cancelled_within_optional_budget(monkeypatch):
    monkeypatch.setattr(goal_evaluator, "SUGGESTION_TIMEOUT_SECONDS", 0.01, raising=False)
    cancelled = asyncio.Event()

    async def stalled(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    client = MagicMock(generate=stalled)
    evaluator = GoalEvaluator(client, {})
    async with asyncio.timeout(1):
        assert await evaluator.generate_suggestions([{"role": "user", "content": "Done"}]) is None
    assert cancelled.is_set()


@pytest.mark.unit
async def test_suggestion_cancellation_propagates_to_caller():
    entered = asyncio.Event()
    cancelled = asyncio.Event()

    async def stalled(**kwargs):
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    evaluator = GoalEvaluator(MagicMock(generate=stalled), {})
    task = asyncio.create_task(
        evaluator.generate_suggestions([{"role": "user", "content": "Done"}])
    )
    await entered.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert cancelled.is_set()


@pytest.mark.unit
async def test_timely_suggestions_remain_available():
    client = MagicMock(
        generate=AsyncMock(return_value={"content": '["First", "Second", "Third", "Fourth"]'})
    )
    assert await GoalEvaluator(client, {}).generate_suggestions(
        [{"role": "user", "content": "Done"}]
    ) == ["First", "Second", "Third"]


@pytest.mark.unit
async def test_completed_plan_settles_despite_stalled_suggestions(monkeypatch):
    monkeypatch.setattr(goal_evaluator, "SUGGESTION_TIMEOUT_SECONDS", 0.01)
    cancelled = asyncio.Event()

    async def stalled(**kwargs):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    processor = SessionProcessor(
        config=ProcessorConfig(
            model="test-model",
            runtime_context={"effective_mode": "plan"},
            loop_resolver=BuiltinAgentLoopResolverV2(
                loop_id="builtin-react",
                plugin_id="memstack-kernel",
                implementation=MagicMock(),
                lifecycle_notifier=MagicMock(),
            ),
        ),
        tools=[],
    )
    processor._goal_evaluator._llm_client = MagicMock(generate=stalled)
    processor._pending_completion_status = "goal_achieved:llm_self_check"
    async with asyncio.timeout(1):
        events = [
            event
            async for event in processor._emit_completion_events(
                ProcessorResult.COMPLETE, "planning-session", [{"role": "user", "content": "Plan"}]
            )
        ]
    assert [event.event_type.value for event in events] == ["status", "complete"]
    assert processor.state == ProcessorState.COMPLETED
    assert cancelled.is_set()
