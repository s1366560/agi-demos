"""Actual LiteLLM response objects must cross the adapter as JSON tool calls."""

import json
from datetime import datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from litellm import ModelResponse

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.agent.processor.goal_evaluator import (
    GOAL_COMPLETION_JUDGE_TOOL_V2,
    GoalEvaluator,
)
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient


@pytest.mark.parametrize(
    ("first_finish_reason", "valid_retry"),
    [
        (None, True),
        ("length", True),
        ("stop", True),
        ("length", False),
        ("stop_then_length", True),
        ("stop_then_length", False),
    ],
)
async def test_real_litellm_tool_call_objects_reach_structured_goal_judge(
    first_finish_reason, valid_retry
):
    raw = ModelResponse(
        choices=[
            {
                "finish_reason": "tool_calls",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": "goal-call",
                            "type": "function",
                            "function": {
                                "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                                "arguments": json.dumps(
                                    {
                                        "goal_achieved": True,
                                        "rationale": "Requested planning is complete.",
                                    }
                                ),
                            },
                        }
                    ],
                },
            }
        ],
        usage={"prompt_tokens": 24, "completion_tokens": 42, "total_tokens": 66},
    )
    assert not isinstance(raw.choices[0].message.tool_calls[0], dict)
    provider = ProviderConfig(
        id=uuid4(),
        name="test-provider",
        provider_type=ProviderType.OPENAI,
        api_key_encrypted="unused",
        llm_model="gpt-4o",
        llm_small_model="gpt-4o-mini",
        embedding_model="text-embedding-3-small",
        config={},
        is_active=True,
        is_default=False,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    client = LiteLLMClient(
        provider_config=provider,
        config=LLMConfig(api_key="test_key", model="gpt-4o", small_model="gpt-4o-mini"),
        cache=False,
    )
    audits = []
    with patch.object(client, "_execute_with_resilience", AsyncMock(return_value=raw)):
        normalized = await client.generate(
            messages=[{"role": "user", "content": "Verify completion"}],
            tools=[
                {
                    "type": "function",
                    "function": {
                        "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                        "parameters": {"type": "object"},
                    },
                }
            ],
        )
        assert normalized["finish_reason"] == "tool_calls"
        assert normalized["usage"]["output_tokens"] == 42
        assert isinstance(normalized["tool_calls"][0], dict)
        json.dumps(normalized)
    truncated = ModelResponse(
        choices=[
            {
                "finish_reason": "stop"
                if first_finish_reason == "stop_then_length"
                else first_finish_reason or "stop",
                "message": {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [],
                },
            }
        ],
        usage={"prompt_tokens": 24, "completion_tokens": 192, "total_tokens": 216},
    )
    responses = (
        [raw] if first_finish_reason is None else [truncated, raw if valid_retry else truncated]
    )

    if first_finish_reason == "stop_then_length":
        late_truncation = ModelResponse(
            choices=[
                {
                    "finish_reason": "length",
                    "message": {"role": "assistant", "content": None, "tool_calls": []},
                }
            ]
        )
        responses = [truncated, late_truncation, raw if valid_retry else late_truncation]

    async def execute(operation):
        return await operation()

    with (
        patch.object(client, "_execute_with_resilience", execute),
        patch("litellm.acompletion", AsyncMock(side_effect=responses)) as completion,
    ):
        evaluator = GoalEvaluator(client, {}, audit_sink=audits.append)
        judgment = await evaluator._call_goal_check_llm("The requested plan is complete.")
    expected_budgets = (
        [192]
        if first_finish_reason is None
        else [192, 4096 if first_finish_reason == "length" else 192]
    )
    if first_finish_reason == "stop_then_length":
        expected_budgets = [192, 192, 4096]
    assert [call.kwargs["max_tokens"] for call in completion.call_args_list] == expected_budgets
    assert all(
        call.kwargs["tool_choice"]["function"]["name"] == GOAL_COMPLETION_JUDGE_TOOL_V2
        for call in completion.call_args_list
    )
    if not valid_retry:
        assert judgment is None
        assert audits == []
    else:
        assert judgment is not None
        assert judgment.achieved is True
        assert len(audits) == 1


@pytest.mark.parametrize("last_result", ["tool_calls", "length", "stop"])
async def test_second_attempt_truncation_gets_one_expanded_budget(last_result):
    """Replay the native stop/length sequence; only a real call can recover."""
    valid = {
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                    "arguments": json.dumps(
                        {"goal_achieved": True, "rationale": "Objective satisfied."}
                    ),
                },
            }
        ],
    }
    final = (
        valid
        if last_result == "tool_calls"
        else {
            "finish_reason": last_result,
            "tool_calls": [],
        }
    )
    client = AsyncMock()
    client.generate.side_effect = [
        {"finish_reason": "stop", "tool_calls": []},
        {"finish_reason": "length", "tool_calls": []},
        final,
    ]
    audits = []
    evaluator = GoalEvaluator(client, {}, audit_sink=audits.append)
    result = await evaluator._call_goal_check_llm("The child returned its requested marker.")
    assert [call.kwargs["max_tokens"] for call in client.generate.call_args_list] == [
        192,
        192,
        4096,
    ]
    assert all(
        call.kwargs["tool_choice"]["function"]["name"] == GOAL_COMPLETION_JUDGE_TOOL_V2
        for call in client.generate.call_args_list
    )
    assert (result is not None) == (last_result == "tool_calls")
    assert len(audits) == int(last_result == "tool_calls")
