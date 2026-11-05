"""Failed or interrupted turns do not send empty assistant placeholders to providers."""

from __future__ import annotations

import asyncio
import copy
import json
from contextlib import aclosing
from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.llm.litellm.litellm_client import (
    LiteLLMClient,
    _sanitize_tool_call_adjacency,
)

pytestmark = pytest.mark.unit


def tool_call(call_id):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "neutral_fixture", "arguments": "{}"},
    }


@pytest.mark.parametrize("content", [None, "", []])
def test_empty_failed_assistant_placeholder_is_omitted_without_mutating_history(content):
    history = [
        {"role": "user", "content": "initial"},
        {"role": "assistant", "content": content},
        {"role": "user", "content": "retry"},
    ]
    original = copy.deepcopy(history)
    assert _sanitize_tool_call_adjacency(history) == [history[0], history[2]]
    assert history == original


def test_incomplete_tools_leave_no_empty_assistant_but_complete_exchanges_remain_exact():
    history = [
        {"role": "assistant", "content": None, "tool_calls": [tool_call("complete")]},
        {"role": "tool", "content": "", "tool_call_id": "complete"},
        {"role": "assistant", "content": None, "tool_calls": [tool_call("missing")]},
        {"role": "user", "content": "retry"},
    ]
    original = copy.deepcopy(history)
    assert _sanitize_tool_call_adjacency(history) == [*history[:2], history[-1]]
    assert history == original


@pytest.mark.parametrize(
    "payload",
    [
        {"content": "  exact whitespace\n"},
        {"content": [{"type": "text", "text": "neutral"}]},
        {"content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,YQ=="}}]},
        {"content": [{"type": "input_audio", "input_audio": {"data": "YQ==", "format": "wav"}}]},
        {"reasoning_content": " exact reasoning\n"},
        {"reasoning": " exact reasoning\n"},
        {"reasoning_details": [{"type": "reasoning.encrypted", "data": "opaque"}]},
        {"thinking_blocks": [{"type": "thinking", "thinking": "neutral", "signature": "opaque"}]},
        {"refusal": " exact refusal\n"},
        {"audio": {"id": "neutral-audio-output"}},
    ],
)
def test_nonempty_assistant_payloads_survive_conversion_and_sanitation(payload):
    message = {"role": "assistant", "content": None, **payload}
    original = copy.deepcopy(message)
    converted = LiteLLMClient._convert_message(message)
    assert _sanitize_tool_call_adjacency([converted]) == [converted]
    for field, value in payload.items():
        assert converted[field] == value
    assert message == original


async def serve_history(reader, writer, received):
    await reader.readline()
    headers = {}
    while line := await reader.readline():
        if line == b"\r\n":
            break
        name, value = line.decode().split(":", 1)
        headers[name.lower()] = value.strip()
    body = json.loads(await reader.readexactly(int(headers["content-length"])))
    received.append(body)
    messages = body["messages"]
    invalid = any(
        message["role"] == "assistant"
        and not any(
            message.get(field)
            for field in (
                "content",
                "tool_calls",
                "reasoning_content",
                "refusal",
                "audio",
            )
        )
        for message in messages
    )
    if invalid:
        payload = json.dumps({"error": {"message": "assistant must not be empty"}}).encode()
        status, mime = "400 Bad Request", "application/json"
    elif body.get("stream"):
        chunk = {
            "id": "neutral",
            "model": "history-fixture",
            "object": "chat.completion.chunk",
            "created": 1,
            "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
        }
        payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
        status, mime = "200 OK", "text/event-stream"
    else:
        payload = json.dumps(
            {
                "id": "neutral",
                "model": "history-fixture",
                "object": "chat.completion",
                "created": 1,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            }
        ).encode()
        status, mime = "200 OK", "application/json"
    writer.write(
        f"HTTP/1.1 {status}\r\nContent-Type: {mime}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
        + payload
    )
    await writer.drain()
    writer.close()
    await writer.wait_closed()


@pytest.mark.parametrize("streaming", [False, True])
async def test_actual_http_retry_history_keeps_tool_reasoning_and_media_payloads(streaming):
    received = []

    server = await asyncio.start_server(
        lambda reader, writer: serve_history(reader, writer, received), "127.0.0.1", 0
    )
    try:
        port = server.sockets[0].getsockname()[1]
        provider = ProviderConfig(
            id=uuid4(),
            name="history-fixture",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="fixture-unused",
            llm_model="openai/history-fixture",
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
        messages = [
            {"role": "user", "content": "initial"},
            {"role": "assistant", "content": None, "tool_calls": [tool_call("complete")]},
            {"role": "tool", "content": "", "tool_call_id": "complete"},
            {"role": "assistant", "content": None},
            {"role": "assistant", "content": None, "tool_calls": [tool_call("incomplete")]},
            {"role": "assistant", "content": "", "reasoning_content": " exact reasoning\n"},
            {"role": "assistant", "content": [{"type": "text", "text": " exact part\n"}]},
            {"role": "user", "content": "retry"},
        ]
        original = copy.deepcopy(messages)
        if streaming:
            async with aclosing(client.generate_stream(messages)) as stream:
                chunks = [chunk async for chunk in stream]
            assert chunks
        else:
            assert (await client.generate(messages))["content"] == "ok"
        assert len(received) == 1
        actual = received[0]["messages"]
        assert [message["role"] for message in actual] == [
            "user",
            "assistant",
            "tool",
            "assistant",
            "assistant",
            "user",
        ]
        assert actual[1]["tool_calls"] == messages[1]["tool_calls"]
        assert actual[2] == messages[2]
        assert actual[3]["reasoning_content"] == messages[5]["reasoning_content"]
        assert actual[4] == messages[6]
        assert messages == original
    finally:
        server.close()
        await server.wait_closed()
