"""Exact declarations and real HTTP requests for native recording input."""

from __future__ import annotations

import asyncio
import base64
import json
from contextlib import aclosing
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.application.services.provider_service import ProviderService
from src.domain.llm_providers.audio_input import validate_audio_input_declaration
from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import (
    ProviderConfigCreate,
    ProviderConfigUpdate,
    ProviderType,
    _public_provider_response_config,
    validate_provider_request_config,
)
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.llm.resilience.rate_limiter import ProviderRateLimiter, RateLimitConfig
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.tests.unit.infrastructure.agent import test_native_audio_input as audio_fixtures
from src.tests.unit.infrastructure.agent.test_native_audio_input import persist

pytestmark = pytest.mark.unit


@pytest.fixture
def harness(monkeypatch):
    yield from audio_fixtures.harness.__wrapped__(monkeypatch)


@pytest.mark.parametrize("value", ["model", True, [""], [" model"], ["model", "model"], [1]])
def test_malformed_audio_declaration_rejected(value):
    with pytest.raises(ValidationError):
        validate_provider_request_config({"audio_input_models": value})


def test_audio_declaration_round_trips_public_config_without_secrets():
    config = validate_provider_request_config({"audio_input_models": ["exact"]})
    assert config == {"audio_input_models": ["exact"]}
    assert _public_provider_response_config({**config, "secret": "private"}) == config
    assert "audio_input_models" not in validate_provider_request_config({})


@pytest.mark.parametrize(
    "provider,declared,roster",
    [
        ("anthropic", ["exact"], ["exact"]),
        ("openai", ["not-configured"], ["exact"]),
    ],
)
def test_audio_declaration_requires_supported_adapter_and_configured_exact_model(
    provider, declared, roster
):
    with pytest.raises(ValueError):
        validate_audio_input_declaration(provider, {"audio_input_models": declared}, roster)


def client_for(provider):
    with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
        return LiteLLMClient(
            LLMConfig(api_key="fixture-local-only", model=provider.llm_model),
            provider,
            cache=False,
        )


def test_model_name_never_enables_audio_and_provider_prefix_cannot_escape_adapter(harness):
    client = client_for(harness.provider)
    assert client.supports_audio_input("exact-audio-model")
    assert not client.supports_audio_input("exact-audio-model-2")
    assert not client.supports_audio_input("gpt-4o-audio-preview")
    harness.provider.config = {}
    assert not client.supports_audio_input("exact-audio-model")
    harness.provider.config = {"audio_input_models": ["anthropic/exact"]}
    harness.provider.llm_model = "anthropic/exact"
    assert not client.supports_audio_input("anthropic/exact")
    harness.provider.provider_type = ProviderType.ANTHROPIC
    harness.provider.config = {"audio_input_models": ["exact-audio-model"]}
    assert not client.supports_audio_input("exact-audio-model")


async def test_selected_model_override_omits_unsupported_audio_before_http(harness):
    _, _, messages = await persist(harness)
    client = client_for(harness.provider)
    response = type("Response", (), {"choices": [{"message": {"content": "ok"}}]})()
    with patch("litellm.acompletion", AsyncMock(return_value=response)) as send:
        await client.generate(messages, model="different-model")
    payload = send.call_args.kwargs
    assert "input_audio" not in json.dumps(payload["messages"])
    assert "not explicitly enabled" in json.dumps(payload["messages"])
    assert harness.service.byte_reads == 0


async def test_provider_create_and_update_validate_declaration_against_final_model_roster(harness):
    repository = AsyncMock()
    repository.get_by_name.return_value = None
    repository.create.return_value = harness.provider
    repository.get_by_id.return_value = harness.provider
    repository.update.return_value = harness.provider
    service = ProviderService(repository)
    service.resolution_service = MagicMock()
    valid = ProviderConfigCreate(
        name="audio",
        provider_type=ProviderType.OPENAI,
        api_key="fixture-local-only",
        llm_model="exact-audio-model",
        config={"audio_input_models": ["exact-audio-model"]},
    )
    assert await service.create_provider(valid) is harness.provider
    repository.create.assert_awaited_once()
    with pytest.raises(ValueError, match="exact configured model"):
        await service.update_provider(
            harness.provider.id, ProviderConfigUpdate(llm_model="changed")
        )
    repository.update.assert_not_awaited()
    await service.update_provider(
        harness.provider.id,
        ProviderConfigUpdate(
            llm_model="changed",
            config={"audio_input_models": ["changed"]},
        ),
    )
    assert repository.update.call_args.args[1].config == {"audio_input_models": ["changed"]}


async def test_real_http_normal_and_stream_requests_contain_verified_audio_only(harness):
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
        if body.get("stream"):
            chunk = {
                "id": "fixture",
                "model": "exact-audio-model",
                "object": "chat.completion.chunk",
                "created": 1,
                "choices": [{"index": 0, "delta": {"content": "ok"}, "finish_reason": "stop"}],
            }
            payload = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
            content_type = "text/event-stream"
        else:
            payload = json.dumps(
                {
                    "id": "fixture",
                    "model": "exact-audio-model",
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
            content_type = "application/json"
        writer.write(
            (
                f"HTTP/1.1 200 OK\r\nContent-Type: {content_type}\r\nContent-Length: {len(payload)}\r\nConnection: close\r\n\r\n"
            ).encode()
            + payload
        )
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        harness.provider.base_url = f"http://127.0.0.1:{port}/v1"
        harness.provider.llm_model = "openai/exact-audio-model"
        harness.provider.config = {"audio_input_models": ["openai/exact-audio-model"]}
        harness.stored_provider.base_url = harness.provider.base_url
        harness.stored_provider.config = dict(harness.provider.config)
        # Thirty seconds of audio must not be counted as base64 text tokens.
        harness.content = audio_fixtures.wav_bytes(240_000)
        harness.request["media"]["native-audio"]["size_bytes"] = len(harness.content)
        harness.broker.redis.mget.return_value = [harness.content.hex()]
        _, _, messages = await persist(harness)
        client = client_for(harness.provider)
        response = await asyncio.wait_for(client.generate(messages), 10)
        assert response["content"] == "ok"
        chunks = []
        async with aclosing(client.generate_stream(messages)) as stream:
            async for chunk in stream:
                chunks.append(chunk)
        assert chunks and len(received) == 2
        for request in received:
            block = request["messages"][0]["content"][1]["input_audio"]
            assert block["format"] == "wav"
            assert base64.b64decode(block["data"]) == harness.content
        assert "input_audio" not in json.dumps(messages)
    finally:
        server.close()
        await server.wait_closed()


async def test_real_http_stream_is_closed_when_native_run_is_cancelled(harness):
    started = asyncio.Event()
    closed = asyncio.Event()
    connections = []
    breaker = SimpleNamespace(
        can_execute=lambda: True, record_failure=MagicMock(), record_success=MagicMock()
    )

    async def serve(reader, writer):
        connections.append(writer)
        try:
            await reader.readline()
            length = 0
            while line := await reader.readline():
                if line == b"\r\n":
                    break
                key, value = line.decode().split(":", 1)
                if key.lower() == "content-length":
                    length = int(value.strip())
            await reader.readexactly(length)
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\nTransfer-Encoding: chunked\r\n\r\n"
            )
            await writer.drain()
            started.set()
            assert await reader.read() == b""
            closed.set()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    try:
        port = server.sockets[0].getsockname()[1]
        harness.provider.base_url = f"http://127.0.0.1:{port}/v1"
        harness.provider.llm_model = "openai/exact-audio-model"
        harness.provider.config = {"audio_input_models": ["openai/exact-audio-model"]}
        harness.stored_provider.base_url = harness.provider.base_url
        harness.stored_provider.config = dict(harness.provider.config)
        _, _, messages = await persist(harness)
        client = client_for(harness.provider)

        async def consume():
            async with aclosing(client.generate_stream(messages)) as stream:
                return [chunk async for chunk in stream]

        with patch(
            "src.infrastructure.llm.litellm.litellm_client.get_circuit_breaker_registry",
            return_value=SimpleNamespace(get=lambda _provider: breaker),
        ):
            pending = asyncio.create_task(consume())
            await asyncio.wait_for(started.wait(), 5)
            harness.request["cancelled"] = True
            with pytest.raises(RuntimeV2Error):
                await asyncio.wait_for(pending, 3)
        breaker.record_failure.assert_not_called()
        await asyncio.wait_for(closed.wait(), 3)
    finally:
        for connection in connections:
            connection.close()
        server.close()
        await server.wait_closed()


@pytest.mark.parametrize("streaming", [False, True])
async def test_revoked_audio_leaves_rate_limit_queue_without_poisoning_provider(harness, streaming):
    _, _, messages = await persist(harness)
    client = client_for(harness.provider)
    limiter = ProviderRateLimiter({ProviderType.OPENAI: RateLimitConfig(max_concurrent=1, rpm=0)})
    held = await limiter.acquire(ProviderType.OPENAI)
    breaker = MagicMock()
    breaker.can_execute.return_value = True

    async def invoke():
        if streaming:
            async with aclosing(client.generate_stream(messages)) as source:
                return [chunk async for chunk in source]
        return await client.generate(messages)

    try:
        with (
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_provider_rate_limiter",
                return_value=limiter,
            ),
            patch(
                "src.infrastructure.llm.litellm.litellm_client.get_circuit_breaker_registry",
                return_value=SimpleNamespace(get=lambda _provider: breaker),
            ),
            patch("litellm.acompletion", AsyncMock()) as send,
        ):
            pending = asyncio.create_task(invoke())
            async with asyncio.timeout(2):
                while limiter.get_stats_obj(ProviderType.OPENAI).waiting_requests != 1:
                    await asyncio.sleep(0.01)
            harness.request["cancelled"] = True
            with pytest.raises(RuntimeV2Error):
                await asyncio.wait_for(pending, 2)
            send.assert_not_awaited()
            breaker.record_failure.assert_not_called()
            assert limiter.get_stats_obj(ProviderType.OPENAI).waiting_requests == 0
    finally:
        held.release()
    async with await asyncio.wait_for(limiter.acquire(ProviderType.OPENAI), 1):
        pass
