"""Agent-first structured judgment for conversation title and summary enrichment."""

from __future__ import annotations

import json
import logging
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.conversation_enrichment_judge import (
    CONVERSATION_ENRICHMENT_TOOL_V2,
    ConversationEnrichmentJudgeServiceV2,
    ConversationEnrichmentMessageV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

pytestmark = pytest.mark.unit


def _tool_call(
    *,
    purpose: object = "title",
    value: object = "Structured title",
    rationale: object = "This title captures the supplied conversation topic.",
    name: str = CONVERSATION_ENRICHMENT_TOOL_V2,
    arguments_as_json: bool = True,
) -> dict[str, object]:
    arguments: object = {
        "purpose": purpose,
        "value": value,
        "rationale": rationale,
    }
    if arguments_as_json:
        arguments = json.dumps(arguments)
    return {
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _judge(
    response: dict[str, Any] | Exception,
) -> tuple[ConversationEnrichmentJudgeServiceV2, AsyncMock, AsyncMock]:
    generate = AsyncMock(side_effect=response if isinstance(response, Exception) else None)
    if not isinstance(response, Exception):
        generate.return_value = response
    llm = SimpleNamespace(
        config=SimpleNamespace(model="model-a"),
        generate=generate,
    )
    create = AsyncMock(return_value=llm)
    audit_sink = AsyncMock()
    service = ConversationEnrichmentJudgeServiceV2(
        llm_clients=cast(Any, SimpleNamespace(create=create)),
        db=cast(AsyncSession, SimpleNamespace()),
        tenant_id="tenant-a",
        project_id="project-a",
        user_id="user-a",
        operation_id="operation-a",
        generation=PluginGenerationDescriptorV2(
            profile_id="profile-a",
            generation=41,
            digest="a" * 64,
        ),
        audit_sink=audit_sink,
    )
    return service, create, generate


async def test_judge_requires_one_structured_tool_call_and_records_complete_audit() -> None:
    service, create, generate = _judge({"tool_calls": [_tool_call()]})

    result = await service.judge(
        purpose="title",
        conversation_id="conversation-a",
        messages=(
            ConversationEnrichmentMessageV2(
                role="user",
                content="Plan the structured conversation generation migration",
            ),
        ),
    )

    assert result.value == "Structured title"
    assert result.rationale == "This title captures the supplied conversation topic."
    assert result.audit.agent_id == "tenant-llm:model-a"
    assert result.audit.tool_name == CONVERSATION_ENRICHMENT_TOOL_V2
    assert result.audit.input_json["conversation_id"] == "conversation-a"
    assert result.audit.input_json["operation_id"] == "operation-a"
    assert result.audit.input_json["generation"] == {
        "profile_id": "profile-a",
        "generation": 41,
        "digest": "a" * 64,
    }
    assert result.audit.output_json == {
        "purpose": "title",
        "value": "Structured title",
        "rationale": "This title captures the supplied conversation topic.",
    }
    assert result.audit.latency_ms >= 0
    create.assert_awaited_once_with(db=service.db, tenant_id="tenant-a")
    call = generate.await_args.kwargs
    assert call["tool_choice"] == {
        "type": "function",
        "function": {"name": CONVERSATION_ENRICHMENT_TOOL_V2},
    }
    assert call["tools"][0]["function"]["name"] == CONVERSATION_ENRICHMENT_TOOL_V2
    assert "Plan the structured conversation generation migration" in call["messages"][1].content
    service.audit_sink.assert_awaited_once_with(result.audit)


async def test_judge_accepts_provider_tool_call_objects_via_model_dump() -> None:
    class ProviderToolCall:
        def model_dump(self) -> dict[str, object]:
            return _tool_call()

    service, _create, _generate = _judge({"tool_calls": [ProviderToolCall()]})

    result = await service.judge(
        purpose="title",
        conversation_id="conversation-a",
        messages=(ConversationEnrichmentMessageV2(role="user", content="Input"),),
    )

    assert result.value == "Structured title"


@pytest.mark.parametrize(
    ("response", "expected_code"),
    [
        ({"content": "free text fallback"}, "conversation_enrichment_tool_call_required"),
        (
            {"tool_calls": [_tool_call(), _tool_call()]},
            "conversation_enrichment_tool_call_count_invalid",
        ),
        (
            {"tool_calls": [_tool_call(name="wrong_tool")]},
            "conversation_enrichment_tool_call_unauthorized",
        ),
        (
            {"tool_calls": [_tool_call(purpose="summary")]},
            "conversation_enrichment_purpose_mismatch",
        ),
        (
            {"tool_calls": [_tool_call(value={"not": "text"}, arguments_as_json=False)]},
            "conversation_enrichment_value_invalid",
        ),
        (
            {"tool_calls": [_tool_call(value="x" * 51)]},
            "conversation_enrichment_value_invalid",
        ),
        (
            {"tool_calls": [_tool_call(rationale=" ")]},
            "conversation_enrichment_rationale_required",
        ),
    ],
)
async def test_judge_fails_closed_for_invalid_tool_responses(
    response: dict[str, Any],
    expected_code: str,
) -> None:
    service, _create, _generate = _judge(response)

    with pytest.raises(RuntimeV2Error) as error:
        await service.judge(
            purpose="title",
            conversation_id="conversation-a",
            messages=(ConversationEnrichmentMessageV2(role="user", content="Input"),),
        )

    assert error.value.code == expected_code
    service.audit_sink.assert_not_awaited()


async def test_judge_wraps_llm_failure_without_audit_or_free_text_fallback() -> None:
    service, _create, _generate = _judge(RuntimeError("provider secret"))

    with pytest.raises(RuntimeV2Error) as error:
        await service.judge(
            purpose="summary",
            conversation_id="conversation-a",
            messages=(ConversationEnrichmentMessageV2(role="assistant", content="Input"),),
        )

    assert error.value.code == "conversation_enrichment_judge_failed"
    assert "provider secret" not in str(error.value)
    service.audit_sink.assert_not_awaited()


async def test_summary_judgment_bounds_input_at_3000_characters_without_reordering() -> None:
    service, _create, generate = _judge(
        {
            "tool_calls": [
                _tool_call(
                    purpose="summary",
                    value="Structured summary",
                )
            ]
        }
    )

    await service.judge(
        purpose="summary",
        conversation_id="conversation-a",
        messages=(
            ConversationEnrichmentMessageV2(role="user", content="a" * 2000),
            ConversationEnrichmentMessageV2(role="assistant", content="b" * 2000),
        ),
    )

    payload = json.loads(generate.await_args.kwargs["messages"][1].content)
    assert [message["role"] for message in payload["messages"]] == ["user", "assistant"]
    assert len(payload["messages"][0]["content"]) == 2000
    assert len(payload["messages"][1]["content"]) == 1000


async def test_default_audit_log_has_required_fields_and_redacts_message_content(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret_message = "user supplied secret must not enter logs"
    service, _create, _generate = _judge({"tool_calls": [_tool_call()]})
    service = replace(service, audit_sink=None)

    with caplog.at_level(logging.INFO, logger="agent_decision_audit"):
        result = await service.judge(
            purpose="title",
            conversation_id="conversation-a",
            messages=(ConversationEnrichmentMessageV2(role="user", content=secret_message),),
        )

    record = caplog.records[-1]
    for field_name in ("agent_id", "tool_name", "input", "output", "rationale", "latency_ms"):
        assert hasattr(record, field_name)
    assert secret_message not in json.dumps(record.input)
    assert result.value not in json.dumps(record.output)
    assert record.rationale == result.rationale
