"""Tests for final completion gating in SessionProcessor."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.processor import (
    GoalCheckResult,
    ProcessorConfig,
    SessionProcessor,
)
from src.infrastructure.plugins.v2.agent_loop import (
    AgentLoopRunContextV2,
    BuiltinAgentLoopResolverV2,
)


class _NativeLoop:
    @staticmethod
    def run(context: AgentLoopRunContextV2):
        return context.run_native()


def _processor_config() -> ProcessorConfig:
    return ProcessorConfig(
        model="test-model",
        max_steps=3,
        provider_id="test-provider",
        loop_resolver=BuiltinAgentLoopResolverV2(
            loop_id="builtin-react",
            plugin_id="memstack-kernel",
            implementation=_NativeLoop(),
            lifecycle_notifier=MagicMock(),
        ),
    )


@pytest.mark.unit
class TestProcessorCompletionGate:
    """Final COMPLETE must still pass the persisted task gate."""

    @pytest.mark.asyncio
    async def test_process_blocks_complete_when_final_task_gate_fails(self) -> None:
        processor = SessionProcessor(
            config=_processor_config(),
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
                "conversation_id": None,
                "runtime_context": {},
                "task_authority": None,
                "workspace_id": None,
                "workspace_session_role": None,
                "result": "STOP",
            },
        )

    @pytest.mark.asyncio
    async def test_process_allows_llm_task_reconciliation_to_bypass_stale_gate(self) -> None:
        processor = SessionProcessor(
            config=_processor_config(),
            tools=[],
        )

        async def _mock_process_step(session_id, messages):
            if False:
                yield {"type": "noop", "data": {}}

        processor._process_step = _mock_process_step  # type: ignore[method-assign]
        processor._goal_evaluator.evaluate_goal_completion = AsyncMock(  # type: ignore[method-assign]
            return_value=GoalCheckResult(achieved=True, source="llm_task_reconciliation")
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

        assert "error" not in event_types
        assert "complete" in event_types
        assert "goal_achieved:llm_task_reconciliation" in status_values
        processor._goal_evaluator.evaluate_task_completion_gate.assert_not_awaited()  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_process_blocks_complete_when_task_events_seen_without_todoread(self) -> None:
        processor = SessionProcessor(
            config=_processor_config(),
            tools=[],
        )

        async def _mock_process_step(session_id, messages):
            yield {
                "type": "task_list_updated",
                "data": {"tasks": [{"id": "t1", "status": "pending"}]},
            }

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


@pytest.mark.parametrize("has_task_reader", [False, True])
async def test_plan_can_finish_with_pending_execution_tasks(has_task_reader) -> None:
    from types import SimpleNamespace

    config = _processor_config()
    config.runtime_context = {"effective_mode": "plan"}
    processor = SessionProcessor(config=config, tools=[])
    evaluator = processor._goal_evaluator
    if has_task_reader:
        evaluator._tools["todoread"] = MagicMock()
    evaluator._llm_client = MagicMock()
    evaluator._load_session_tasks = AsyncMock(return_value=[{"status": "pending"}])
    evaluator._call_goal_check_llm = AsyncMock(
        return_value=SimpleNamespace(
            achieved=True, rationale="The plan is ready for approval; execution remains pending."
        )
    )
    evaluator.generate_suggestions = AsyncMock(return_value=None)
    processor._notify_plugin_hook = AsyncMock(return_value={})

    async def step(_session_id, _messages):
        processor._saw_task_events = True
        if False:
            yield {}

    processor._process_step = step
    events = [
        event
        async for event in processor.process(
            session_id="plan-session", messages=[{"role": "user", "content": "Prepare a plan"}]
        )
    ]
    types = [
        event.get("type") if isinstance(event, dict) else event.event_type.value for event in events
    ]
    assert "complete" in types
    assert "error" not in types
    assert not any(
        call.kwargs.get("strict") for call in evaluator._load_session_tasks.await_args_list
    )
    evaluator._call_goal_check_llm.assert_awaited_once()
    assert "Plan mode" in evaluator._call_goal_check_llm.await_args.args[0]
    assert "approval" in evaluator._call_goal_check_llm.await_args.args[0]


async def test_unavailable_goal_judge_stops_without_asking_agent_to_repeat_tools():
    from src.infrastructure.agent.processor.processor import ProcessorResult, ProcessorState

    client = AsyncMock()
    client.generate.return_value = {"content": "", "tool_calls": [], "finish_reason": "stop"}
    processor = SessionProcessor(config=_processor_config(), tools=[])
    processor._goal_evaluator._llm_client = client
    processor.config.runtime_context["effective_mode"] = "plan"
    processor._goal_evaluator._runtime_context["effective_mode"] = "plan"
    events = [
        event
        async for event in processor._evaluate_no_tool_result(
            "judge-unavailable", [{"role": "user", "content": "Produce the plan"}]
        )
    ]
    assert client.generate.await_count == 2
    assert processor._last_process_result is ProcessorResult.STOP
    assert processor._state is ProcessorState.ERROR
    assert [getattr(event, "code", None) for event in events] == ["GOAL_JUDGE_UNAVAILABLE"]
    assert processor._no_progress_steps == 0


async def test_invalid_first_judgment_retries_in_judge_without_main_agent_turn():
    import json

    from src.infrastructure.agent.processor.goal_evaluator import (
        GOAL_COMPLETION_JUDGE_TOOL_V2,
        GoalEvaluator,
    )

    client = AsyncMock()
    client.generate.side_effect = [
        {"tool_calls": [], "finish_reason": "stop"},
        {
            "tool_calls": [
                {
                    "type": "function",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "arguments": json.dumps(
                            {"goal_achieved": True, "rationale": "The plan is ready for approval."}
                        ),
                    },
                }
            ]
        },
    ]
    evaluator = GoalEvaluator(client, {}, runtime_context={"effective_mode": "plan"})
    result = await evaluator.evaluate_goal_completion(
        "retry-judge", [{"role": "user", "content": "Produce a plan"}]
    )
    assert result.achieved
    assert client.generate.await_count == 2
