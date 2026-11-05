"""A persisted backlog cannot override this turn's authorized scope."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.processor.goal_evaluator import GoalEvaluator
from src.infrastructure.agent.processor.processor import ProcessorResult, ProcessorState
from src.tests.unit.infrastructure.agent.processor.test_processor_goal_completion import (
    create_todoread_tool,
    goal_judgment_response,
)

pytestmark = pytest.mark.unit


def _backlog():
    return [
        {"id": f"task-{index}", "status": "completed" if index < 2 else "pending"}
        for index in range(13)
    ]


def _messages():
    return [
        {"role": "user", "content": "只恢复旧清单状态为待办，本轮不要执行原清单。"},
        {"role": "assistant", "content": "清单现为 2 项完成、11 项待办，未执行原清单。"},
    ]


@pytest.mark.parametrize("entrypoint", ["goal", "final_gate"])
async def test_current_ledger_restoration_can_finish_without_executing_pending_backlog(entrypoint):
    tasks = _backlog()
    snapshot = deepcopy(tasks)
    client = AsyncMock()
    client.generate.return_value = goal_judgment_response(
        achieved=True,
        rationale="The requested state restoration is complete; backlog execution is excluded.",
    )
    mutation = AsyncMock(side_effect=AssertionError("Completion must not mutate tasks"))
    evaluator = GoalEvaluator(
        client, {"todoread": create_todoread_tool(tasks), "todowrite": mutation}
    )
    evaluate = (
        evaluator.evaluate_goal_completion
        if entrypoint == "goal"
        else evaluator.evaluate_task_completion_gate
    )
    result = await evaluate("session", _messages())
    assert result is not None and result.achieved
    assert result.source == "llm_task_reconciliation"
    assert tasks == snapshot
    mutation.assert_not_called()
    client.generate.assert_awaited_once()


@pytest.mark.parametrize("failure", ["missing_client", "missing_tool_call", "incomplete"])
async def test_unavailable_judge_stops_pending_backlog_without_continuation_guidance(failure):
    client = None if failure == "missing_client" else AsyncMock()
    if client is not None:
        client.generate.return_value = {
            "tool_calls": [],
            "finish_reason": "length" if failure == "incomplete" else "stop",
        }
    processor = SessionProcessor(
        config=ProcessorConfig(model="unused", llm_client=client),
        tools=[create_todoread_tool(_backlog())],
    )
    events = [event async for event in processor._evaluate_no_tool_result("session", _messages())]
    assert processor._last_process_result is ProcessorResult.STOP
    assert processor._state is ProcessorState.ERROR
    assert [getattr(event, "code", None) for event in events] == ["GOAL_JUDGE_UNAVAILABLE"]
    assert not processor._response_instructions
    assert processor._no_progress_steps == 0


async def test_valid_negative_judgment_preserves_current_scope_reason():
    client = AsyncMock()
    client.generate.return_value = goal_judgment_response(
        achieved=False, rationale="One requested status restoration is still missing."
    )
    evaluator = GoalEvaluator(client, {"todoread": create_todoread_tool(_backlog())})
    result = await evaluator.evaluate_goal_completion("session", _messages())
    assert not result.achieved and not result.should_stop
    assert result.source == "llm_self_check"
    assert result.reason == "One requested status restoration is still missing."


@pytest.mark.parametrize("status", ["failed", "completed"])
@pytest.mark.parametrize("scope_complete", [False, True])
async def test_historical_terminal_status_does_not_decide_current_scope(status, scope_complete):
    client = AsyncMock()
    client.generate.return_value = goal_judgment_response(
        achieved=scope_complete,
        rationale="Current scoped request is complete."
        if scope_complete
        else "Current requested verification is still failing.",
    )
    evaluator = GoalEvaluator(
        client,
        {"todoread": create_todoread_tool([{"id": "historical", "status": status}])},
    )
    result = await evaluator.evaluate_goal_completion(
        "session",
        [{"role": "user", "content": "Inspect the current result; retain the task ledger."}],
    )
    assert result.achieved is scope_complete
    assert result.source == ("llm_task_reconciliation" if scope_complete else "llm_self_check")
    client.generate.assert_awaited_once()


async def test_truncated_judgment_retries_with_budget_before_finishing_current_scope():
    client = AsyncMock()
    client.generate.side_effect = [
        {"finish_reason": "length", "tool_calls": []},
        goal_judgment_response(
            achieved=True, rationale="Only the requested status restoration is complete."
        ),
    ]
    evaluator = GoalEvaluator(client, {"todoread": create_todoread_tool(_backlog())})
    result = await evaluator.evaluate_goal_completion("session", _messages())
    assert result.achieved and result.source == "llm_task_reconciliation"
    assert [call.kwargs["max_tokens"] for call in client.generate.await_args_list] == [192, 4096]


async def test_final_gate_receives_current_messages_and_surfaces_judge_unavailable():
    processor = SessionProcessor(
        config=ProcessorConfig(model="unused"), tools=[create_todoread_tool(_backlog())]
    )
    processor._goal_evaluator.evaluate_task_completion_gate = AsyncMock(
        return_value=GoalEvaluator._goal_judge_unavailable_result()
    )
    messages = _messages()
    events = [
        event
        async for event in processor._emit_completion_events(
            ProcessorResult.COMPLETE, "session", messages
        )
    ]
    processor._goal_evaluator.evaluate_task_completion_gate.assert_awaited_once_with(
        "session", messages
    )
    assert processor._last_process_result is ProcessorResult.STOP
    assert "GOAL_JUDGE_UNAVAILABLE" in [getattr(event, "code", None) for event in events]
    assert all(getattr(event, "event_type", None).value != "complete" for event in events)
