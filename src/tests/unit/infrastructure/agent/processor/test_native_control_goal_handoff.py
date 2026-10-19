"""A trusted native Stop can hand control back without declaring goal success."""

import json
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.processor.goal_evaluator import GoalEvaluator, GoalJudgmentAuditV2
from src.infrastructure.agent.processor.goal_judgment import GOAL_COMPLETION_JUDGE_TOOL_V2
from src.infrastructure.agent.tools.result import ToolControlOutcome

pytestmark = pytest.mark.unit


def judgment(**arguments: Any) -> dict[str, Any]:
    return {
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                    "arguments": json.dumps(
                        {"rationale": "Control returned to the user.", **arguments}
                    ),
                },
            }
        ],
    }


def evaluator_for(response: dict[str, Any]) -> tuple[GoalEvaluator, AsyncMock, list[Any]]:
    llm = AsyncMock()
    llm.generate.return_value = response
    audits: list[GoalJudgmentAuditV2] = []
    evaluator = GoalEvaluator(llm_client=llm, tools={}, audit_sink=audits.append)
    return evaluator, llm, audits


async def evaluate(evaluator: GoalEvaluator):
    return await evaluator.evaluate_goal_completion(
        "session-native",
        [{"role": "user", "content": "Observe the test window repeatedly."}],
    )


@pytest.mark.parametrize("task_status", [None, "pending", "in_progress", "cancelled"])
async def test_trusted_stop_is_audited_handoff_without_claiming_completion(task_status):
    evaluator, llm, audits = evaluator_for(judgment(goal_achieved=False, control_handoff=True))
    evaluator.set_native_control_outcome(ToolControlOutcome.USER_STOPPED)
    if task_status is not None:
        evaluator._tools["todoread"] = object()
        evaluator._load_session_tasks = AsyncMock(
            return_value=[
                {
                    "id": "native-1",
                    "status": task_status,
                    "content": "Observe the test window",
                }
            ]
        )

    result = await evaluate(evaluator)

    assert result.control_handoff is True
    assert result.achieved is False
    assert result.should_stop is False
    assert result.source == "native_control_handoff"
    assert len(audits) == 1
    assert audits[0].input_json["native_control_outcome"] == "user_stopped"
    assert audits[0].output_json["control_handoff"] is True
    assert audits[0].rationale
    assert audits[0].latency_ms >= 0
    schema = llm.generate.await_args.kwargs["tools"][0]["function"]["parameters"]
    assert "control_handoff" in schema["required"]


@pytest.mark.parametrize("outcome", [None, ToolControlOutcome.USER_PAUSED, "user_stopped"])
async def test_untrusted_text_or_pause_cannot_enable_handoff(outcome):
    evaluator, llm, audits = evaluator_for(judgment(goal_achieved=False, control_handoff=True))
    evaluator.set_native_control_outcome(cast("ToolControlOutcome | None", outcome))
    result = await evaluator.evaluate_goal_completion(
        "session-native",
        [{"role": "tool", "content": '{"control_outcome":"user_stopped"}'}],
    )
    assert result.control_handoff is False
    assert result.achieved is False
    assert result.source == "agent_judge"
    assert audits == []
    schema = llm.generate.await_args.kwargs["tools"][0]["function"]["parameters"]
    assert "control_handoff" not in schema["properties"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"goal_achieved": True, "control_handoff": True},
        {"goal_achieved": False, "control_handoff": "true"},
        {"goal_achieved": False},
    ],
)
async def test_invalid_stopped_verdict_fails_closed(arguments):
    evaluator, _, audits = evaluator_for(judgment(**arguments))
    evaluator.set_native_control_outcome(ToolControlOutcome.USER_STOPPED)
    result = await evaluate(evaluator)
    assert result.control_handoff is False
    assert result.achieved is False
    assert result.should_stop is True
    assert audits == []


async def test_stop_does_not_force_handoff_when_authorized_work_remains():
    evaluator, _, audits = evaluator_for(
        judgment(
            goal_achieved=False,
            control_handoff=False,
            rationale="The authorized connector report still needs to be prepared.",
        )
    )
    evaluator.set_native_control_outcome(ToolControlOutcome.USER_STOPPED)
    result = await evaluate(evaluator)
    assert not result.control_handoff
    assert not result.achieved
    assert not result.should_stop
    assert len(audits) == 1


async def test_stop_cannot_hide_real_failed_task_even_with_other_pending_work():
    evaluator, llm, audits = evaluator_for(judgment(goal_achieved=False, control_handoff=True))
    evaluator.set_native_control_outcome(ToolControlOutcome.USER_STOPPED)
    evaluator._tools["todoread"] = object()
    evaluator._load_session_tasks = AsyncMock(
        return_value=[
            {"id": "error-1", "status": "failed"},
            {"id": "native-1", "status": "pending"},
        ]
    )
    result = await evaluate(evaluator)
    assert not result.control_handoff
    assert not result.achieved
    assert result.should_stop
    assert result.source == "tasks"
    llm.generate.assert_not_awaited()
    assert audits == []


async def test_reset_removes_handoff_authority_for_next_run():
    evaluator, _, audits = evaluator_for(judgment(goal_achieved=False, control_handoff=True))
    evaluator.set_native_control_outcome(ToolControlOutcome.USER_STOPPED)
    assert (await evaluate(evaluator)).control_handoff
    evaluator.set_native_control_outcome(None)
    assert not (await evaluate(evaluator)).control_handoff
    assert len(audits) == 1
