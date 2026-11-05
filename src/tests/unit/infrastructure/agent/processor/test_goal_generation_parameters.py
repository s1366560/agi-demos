"""Goal judges inherit current generation parameters without weakening structured verdicts."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.agent.processor.goal_evaluator import GoalEvaluator
from src.infrastructure.agent.processor.goal_judgment import GOAL_COMPLETION_JUDGE_TOOL_V2
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.llm.completion_finish import ProviderCompletionError
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

pytestmark = pytest.mark.unit


def verdict():
    return {
        "finish_reason": "tool_calls",
        "tool_calls": [
            {
                "type": "function",
                "function": {
                    "name": GOAL_COMPLETION_JUDGE_TOOL_V2,
                    "arguments": json.dumps(
                        {"goal_achieved": False, "rationale": "Fixture still needs work"}
                    ),
                },
            }
        ],
    }


class Client:
    def __init__(self, *responses):
        self.responses = list(responses or [verdict()])
        self.calls = []

    async def generate(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


async def test_processor_judge_reads_current_model_temperature_and_declared_omission():
    client = Client(verdict(), verdict(), verdict())
    config = ProcessorConfig(model="fixture-first", temperature=1.0, llm_client=client)
    processor = SessionProcessor(config=config, tools=[])
    assert await processor._goal_evaluator._call_goal_check_llm("neutral") is not None
    config.model = "fixture-next"
    config.temperature = 0.4
    assert await processor._goal_evaluator._call_goal_check_llm("neutral") is not None
    config.provider_options = {"__omit_temperature": True}
    assert await processor._goal_evaluator._call_goal_check_llm("neutral") is not None
    assert [(call["model"], call.get("temperature")) for call in client.calls] == [
        ("fixture-first", 1.0),
        ("fixture-next", 0.4),
        ("fixture-next", None),
    ]
    assert client.calls[-1]["_omit_temperature"] is True
    assert all(call.get("tool_choice", "auto") == "auto" for call in client.calls)


async def test_standalone_judge_defers_sampling_to_provider_defaults():
    client = Client()
    result = await GoalEvaluator(client, {})._call_goal_check_llm("neutral")
    assert result is not None
    assert "temperature" not in client.calls[0]
    assert "model" not in client.calls[0]


async def test_provider_options_cannot_replace_judge_protocol_or_budget():
    client = Client(ProviderCompletionError("length"), verdict())
    options = {
        "thinking": {"type": "enabled"},
        "tool_choice": "required",
        "tools": [],
        "messages": [],
        "max_tokens": 999999,
        "max_completion_tokens": 999999,
        "__override_max_tokens": 999999,
        "temperature": 0.0,
        "model": "wrong",
        "stream": True,
        "api_key": "fixture-forged",
        "api_base": "https://invalid.example",
        "base_url": "https://invalid.example",
        "extra_headers": {"Authorization": "fixture-forged"},
    }
    evaluator = GoalEvaluator(
        client,
        {},
        generation_parameters=lambda: {
            "model": "fixture",
            "temperature": 1.0,
            "provider_options": options,
        },
    )
    result = await evaluator._call_goal_check_llm("neutral")
    assert result is not None
    assert [call["max_tokens"] for call in client.calls] == [192, 4096]
    for call in client.calls:
        assert call["model"] == "fixture" and call["temperature"] == 1.0
        assert call.get("tool_choice", "auto") == "auto"
        assert call["tools"][0]["function"]["name"] == GOAL_COMPLETION_JUDGE_TOOL_V2
        assert call["thinking"] == {"type": "enabled"}
        assert "max_completion_tokens" not in call and "stream" not in call
        assert not {"api_key", "api_base", "base_url", "extra_headers"}.intersection(call)
    assert options["tool_choice"] == "required"


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_incomplete_or_filtered_judges_never_become_verdicts(reason):
    client = Client(ProviderCompletionError(reason), ProviderCompletionError(reason))
    audits = []
    result = await GoalEvaluator(client, {}, audit_sink=audits.append)._call_goal_check_llm(
        "neutral"
    )
    assert result is None and audits == []
    assert [call["max_tokens"] for call in client.calls] == (
        [192, 4096] if reason == "length" else [192]
    )


async def test_auto_tool_selection_still_rejects_prose_and_nonexact_calls():
    client = Client({"content": "goal_achieved=true"}, {"tool_calls": []})
    audits = []
    assert (
        await GoalEvaluator(client, {}, audit_sink=audits.append)._call_goal_check_llm("neutral")
        is None
    )
    assert len(client.calls) == 2 and audits == []


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_legacy_incomplete_mapping_cannot_supply_a_partial_verdict(reason):
    partial = verdict()
    partial["finish_reason"] = reason
    client = Client(partial, verdict())
    audits = []
    result = await GoalEvaluator(client, {}, audit_sink=audits.append)._call_goal_check_llm(
        "neutral"
    )
    assert len(audits) == (1 if reason == "length" else 0)
    assert (result is not None) is (reason == "length")
    assert len(client.calls) == (2 if reason == "length" else 1)


async def test_declared_completion_token_parameter_cannot_expand_judge_budget():
    client = Client(ProviderCompletionError("length"), verdict())
    evaluator = GoalEvaluator(
        client,
        {},
        generation_parameters=lambda: {
            "model": "fixture",
            "provider_options": {
                "__use_max_completion_tokens": True,
                "__override_max_tokens": 999999,
            },
        },
    )
    assert await evaluator._call_goal_check_llm("neutral") is not None
    assert [call["max_completion_tokens"] for call in client.calls] == [192, 4096]


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_selected_nested_choice_cannot_supply_an_incomplete_verdict(reason):
    nested = {
        "choices": [{"finish_reason": reason, "message": {"tool_calls": verdict()["tool_calls"]}}]
    }
    client = Client(nested, verdict())
    audits = []
    result = await GoalEvaluator(client, {}, audit_sink=audits.append)._call_goal_check_llm(
        "neutral"
    )
    assert len(audits) == (1 if reason == "length" else 0)
    assert len(client.calls) == (2 if reason == "length" else 1)
    assert (result is not None) is (reason == "length")


@pytest.mark.parametrize("root_calls", [True, False])
async def test_unused_choice_finish_reason_cannot_override_selected_complete_tool_call(root_calls):
    response = verdict() if root_calls else {}
    response["choices"] = [
        {
            "finish_reason": "length" if root_calls else "tool_calls",
            "message": {"tool_calls": verdict()["tool_calls"]},
        },
        {"finish_reason": "content_filter", "message": {}},
    ]
    client = Client(response)
    assert await GoalEvaluator(client, {})._call_goal_check_llm("neutral") is not None
    assert len(client.calls) == 1


async def test_real_http_judge_uses_runtime_sampling_and_one_bounded_truncation_retry():
    received = []

    async def serve(reader, writer):
        await reader.readline()
        headers = {}
        while line := await reader.readline():
            if line == b"\r\n":
                break
            key, value = line.decode().split(":", 1)
            headers[key.lower()] = value.strip()
        body = json.loads(await reader.readexactly(int(headers["content-length"])))
        received.append(body)
        if body.get("temperature") != 1.0 or isinstance(body.get("tool_choice"), dict):
            status = "400 Bad Request"
            payload = {
                "error": {
                    "type": "invalid_request_error",
                    "message": "fixture sampling or forced choice invalid",
                }
            }
        else:
            status = "200 OK"
            payload = {
                "id": "fixture",
                "model": "judge-fixture",
                "object": "chat.completion",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": ""},
                        "finish_reason": "length",
                    }
                ],
            }
            if body["max_tokens"] == 4096:
                payload["choices"][0].update(
                    message={
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [{"id": "fixture-call", **verdict()["tool_calls"][0]}],
                    },
                    finish_reason="tool_calls",
                )
        encoded = json.dumps(payload).encode()
        writer.write(
            f"HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {len(encoded)}\r\nConnection: close\r\n\r\n".encode()
            + encoded
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        provider = ProviderConfig(
            id=uuid4(),
            name="judge-fixture",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="fixture-unused",
            llm_model="openai/judge-fixture",
            base_url=f"http://127.0.0.1:{port}/v1",
            config={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            client = LiteLLMClient(
                LLMConfig(api_key="fixture-local-only", model=provider.llm_model),
                provider,
                cache=False,
            )
        processor = SessionProcessor(
            config=ProcessorConfig(model=provider.llm_model, temperature=1.0, llm_client=client),
            tools=[],
        )
        audits = []
        processor._goal_evaluator._audit_sink = audits.append
        result = await processor._goal_evaluator._call_goal_check_llm("neutral")
        assert result is not None and result.achieved is False and len(audits) == 1
        assert [body["max_tokens"] for body in received] == [192, 4096]
        assert all(
            body["model"] == "judge-fixture" and body["temperature"] == 1.0 for body in received
        )
    finally:
        server.close()
        await server.wait_closed()
