"""Provider attempts persist their final inputs and can replay without plugins."""

from __future__ import annotations

import asyncio
import json
from contextlib import aclosing
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient
from src.infrastructure.plugins.v2.model_request_log import (
    MODEL_REQUEST_PREPARED_EVENT_V2,
    MODEL_REQUEST_SETTLED_EVENT_V2,
    ModelRequestRecorderV2,
    recorded_completion_stream_v2,
    replay_prepared_model_request_v2,
)
from src.infrastructure.plugins.v2.session_event_log import SessionEventLogServiceV2
from src.infrastructure.plugins.v2.session_event_log_types import (
    SessionEventCursorV2,
    SessionEventRecordV2,
)


@dataclass
class _Store:
    records: list[SessionEventRecordV2] = field(default_factory=list)
    fail_append: bool = False

    async def append_stream_events(self, *, conversation_id, message_id, events, correlation_id):
        if self.fail_append:
            raise OSError("storage unavailable")
        for event in events:
            self.records.append(
                SessionEventRecordV2(
                    event_id=str(len(self.records)),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    event_type=event["type"],
                    event_data=event["data"],
                    cursor=SessionEventCursorV2(
                        event_time_us=event["event_time_us"],
                        event_counter=event["event_counter"],
                    ),
                )
            )

    async def read_message_events(self, *, conversation_id, message_id):
        return [
            r
            for r in self.records
            if r.conversation_id == conversation_id and r.message_id == message_id
        ]

    async def last_cursor(self, *, conversation_id):
        return max(
            (r.cursor for r in self.records if r.conversation_id == conversation_id),
            default=SessionEventCursorV2(),
        )

    async def read_events(self, *, conversation_id, after, limit):
        return [
            r
            for r in self.records
            if r.conversation_id == conversation_id and (after is None or r.cursor > after)
        ][:limit]


def _recorder():
    store = _Store()
    log = SessionEventLogServiceV2(
        strategy="ordered-sql-event-log",
        store=store,
        generation_resolver=lambda: PluginGenerationDescriptorV2(
            profile_id="profile",
            generation=4,
            digest="a" * 64,
        ),
    )
    return ModelRequestRecorderV2(
        log=log,
        conversation_id="session",
        message_id="message",
        operation_id="turn",
    ), store


def _install_transport(monkeypatch, send):
    import httpx
    from litellm.llms.custom_httpx.http_handler import AsyncHTTPHandler

    def create_client(self, *, timeout, event_hooks, **kwargs):
        return httpx.AsyncClient(transport=httpx.MockTransport(send), event_hooks=event_hooks)

    monkeypatch.setattr(AsyncHTTPHandler, "create_client", create_client)


def _sse(body):
    import httpx

    text = json.dumps(
        {
            "id": "test",
            "object": "chat.completion.chunk",
            "model": "gpt-4o",
            "created": 1,
            "choices": [{"index": 0, "delta": {"content": "hello"}, "finish_reason": None}],
        }
    )
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        content=f"data: {text}\n\ndata: [DONE]\n\n",
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "model",
    [
        "openai/gpt-4o",
        "anthropic/claude-3-5-sonnet-20241022",
        "gemini/gemini-2.5-flash",
        "deepseek/deepseek-chat",
        "dashscope/qwen-plus",
    ],
)
async def test_exact_provider_body_durable_before_transport_and_replay(monkeypatch, model):
    import httpx
    import litellm

    recorder, store = _recorder()
    sent = []

    async def send(request):
        body = json.loads(request.content)
        sent.append(body)
        prepared = store.records[-1]
        assert prepared.event_type == MODEL_REQUEST_PREPARED_EVENT_V2
        assert prepared.event_data["request"] == body
        assert prepared.event_data["schema_version"] == 1
        assert prepared.event_data["format"] == "provider.http.json/v1"
        # Final provider input survived conversion; auth and endpoint are excluded.
        assert "private-credential" not in json.dumps(prepared.event_data)
        if model.startswith("anthropic/"):
            assert body["system"] == [{"type": "text", "text": "pinned guidance"}]
            assert body["model"] == "claude-3-5-sonnet-20241022"
            assert body["tools"][0]["input_schema"]["type"] == "object"
        elif model.startswith("gemini/"):
            assert "contents" in body and "messages" not in body
            assert "system_instruction" in body or "systemInstruction" in body
        else:
            assert "/" not in body["model"]
        # A provider error still leaves its exact input available for replay.
        return httpx.Response(
            400, json={"error": {"message": "invalid request", "type": "invalid_request_error"}}
        )

    _install_transport(monkeypatch, send)
    with pytest.raises(Exception):
        async for _ in recorded_completion_stream_v2(
            litellm.acompletion,
            {
                "model": model,
                "api_key": "private-credential",
                "api_base": "https://provider.invalid",
                "messages": [
                    {"role": "system", "content": "pinned guidance"},
                    {"role": "user", "content": "hello"},
                ],
                "tools": [
                    {
                        "type": "function",
                        "function": {
                            "name": "read",
                            "parameters": {"type": "object", "properties": {}},
                        },
                    }
                ],
                "max_tokens": 512,
                "stream": True,
            },
            recorder,
        ):
            pass
    assert len(sent) == 1
    assert store.records[-1].event_data["status"] == "failed"
    replacement = SessionEventLogServiceV2(
        strategy="ordered-sql-event-log",
        store=store,
        generation_resolver=lambda: (_ for _ in ()).throw(
            AssertionError("must not resolve generation")
        ),
    )
    assert (
        await replay_prepared_model_request_v2(
            replacement,
            conversation_id="session",
            message_id="message",
            attempt_id=store.records[0].event_data["attempt_id"],
        )
        == sent[0]
    )
    assert await replacement.materialize_model_messages(conversation_id="session") == []


@pytest.mark.unit
async def test_recording_storage_failure_prevents_http_send(monkeypatch):
    import litellm

    recorder, store = _recorder()
    store.fail_append = True
    send = AsyncMock(side_effect=AssertionError("must not send"))
    _install_transport(monkeypatch, send)
    with pytest.raises(Exception):
        async for _ in recorded_completion_stream_v2(
            litellm.acompletion,
            {
                "model": "openai/gpt-4o",
                "api_key": "private-key",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            recorder,
        ):
            pass
    send.assert_not_awaited()


@pytest.mark.unit
async def test_concurrent_attempts_confirm_durable_snapshots_after_cursor_conflict(monkeypatch):
    import litellm

    class ConflictStore(_Store):
        initial_reads = 0

        def __init__(self):
            super().__init__()
            self.both_read = asyncio.Event()

        async def last_cursor(self, *, conversation_id):
            cursor = await super().last_cursor(conversation_id=conversation_id)
            if self.initial_reads < 2:
                self.initial_reads += 1
                if self.initial_reads == 2:
                    self.both_read.set()
                await self.both_read.wait()
            return cursor

        async def append_stream_events(self, **kwargs):
            # The SQL store has UNIQUE(conversation_id, time, counter) and
            # ON CONFLICT DO NOTHING. Reproduce its committed-write behavior.
            events = [
                event
                for event in kwargs["events"]
                if not any(
                    record.conversation_id == kwargs["conversation_id"]
                    and record.cursor.event_time_us == event["event_time_us"]
                    and record.cursor.event_counter == event["event_counter"]
                    for record in self.records
                )
            ]
            await super().append_stream_events(**{**kwargs, "events": events})

    base, _ = _recorder()
    store = ConflictStore()
    recorder = ModelRequestRecorderV2(
        log=SessionEventLogServiceV2(
            strategy="ordered-sql-event-log",
            store=store,
            generation_resolver=base.log.generation_resolver,
        ),
        conversation_id=base.conversation_id,
        message_id=base.message_id,
        operation_id=base.operation_id,
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.model_request_log.time.time_ns", lambda: 1000
    )
    sent = []

    async def send(request):
        body = json.loads(request.content)
        assert any(
            record.event_type == MODEL_REQUEST_PREPARED_EVENT_V2
            and record.event_data["request"] == body
            for record in store.records
        ), "provider received an input without its own durable snapshot"
        sent.append(body)
        return _sse(None)

    _install_transport(monkeypatch, send)

    async def complete(content):
        async for _ in recorded_completion_stream_v2(
            litellm.acompletion,
            {
                "model": "openai/gpt-4o",
                "api_key": "private-key",
                "stream": True,
                "messages": [{"role": "user", "content": content}],
            },
            recorder,
        ):
            pass

    await asyncio.wait_for(asyncio.gather(complete("first"), complete("second")), timeout=20)
    assert len(sent) == 2
    assert len([r for r in store.records if r.event_type == MODEL_REQUEST_PREPARED_EVENT_V2]) == 2
    assert len([r for r in store.records if r.event_type == MODEL_REQUEST_SETTLED_EVENT_V2]) == 2


@pytest.mark.unit
@pytest.mark.parametrize("storage_result", ["dropped", "modified"])
async def test_unconfirmed_or_modified_snapshot_prevents_transport(monkeypatch, storage_result):
    import litellm

    recorder, store = _recorder()
    original_append = store.append_stream_events

    async def incomplete_append(**kwargs):
        if storage_result == "dropped":
            return
        await original_append(**kwargs)
        record = store.records[-1]
        store.records[-1] = replace(
            record, event_data={**record.event_data, "request": {"model": "modified"}}
        )

    monkeypatch.setattr(store, "append_stream_events", incomplete_append)
    send = AsyncMock(side_effect=AssertionError("must not send unrecorded input"))
    _install_transport(monkeypatch, send)
    with pytest.raises(Exception):
        async for _ in recorded_completion_stream_v2(
            litellm.acompletion,
            {
                "model": "openai/gpt-4o",
                "api_key": "private-key",
                "stream": True,
                "messages": [{"role": "user", "content": "exact input"}],
            },
            recorder,
        ):
            pass
    send.assert_not_awaited()


@pytest.mark.unit
async def test_unsupported_agent_transport_is_rejected_before_completion():
    recorder, store = _recorder()
    completion = AsyncMock(side_effect=AssertionError("must not call provider"))
    with pytest.raises(Exception, match="Azure Agents transport"):
        async for _ in recorded_completion_stream_v2(
            completion,
            {
                "model": "azure_ai/agents/test-agent",
                "api_base": "https://example.invalid",
                "api_key": "private-key",
                "stream": True,
                "messages": [{"role": "user", "content": "hi"}],
            },
            recorder,
        ):
            pass
    completion.assert_not_awaited()
    assert store.records == []


@pytest.mark.unit
async def test_retries_have_separate_attempts_and_unknown_provider_fields_are_retained(monkeypatch):
    import httpx
    import litellm

    recorder, store = _recorder()
    calls = 0

    async def send(request):
        nonlocal calls
        calls += 1
        assert json.loads(request.content)["custom_vendor_setting"] == {"enabled": True}
        if calls == 1:
            return httpx.Response(503, json={"error": {"message": "unavailable"}})
        return _sse(None)

    _install_transport(monkeypatch, send)
    kwargs = {
        "model": "openai/gpt-4o",
        "api_key": "private-key",
        "stream": True,
        "messages": [{"role": "user", "content": "hi"}],
        "extra_body": {"custom_vendor_setting": {"enabled": True}},
    }
    with pytest.raises(Exception):
        async for _ in recorded_completion_stream_v2(litellm.acompletion, kwargs, recorder):
            pass
    async for _ in recorded_completion_stream_v2(litellm.acompletion, kwargs, recorder):
        pass
    prepared = [r for r in store.records if r.event_type == MODEL_REQUEST_PREPARED_EVENT_V2]
    settled = [r for r in store.records if r.event_type == MODEL_REQUEST_SETTLED_EVENT_V2]
    assert len({r.event_data["attempt_id"] for r in prepared}) == 2
    assert [r.event_data["status"] for r in settled] == ["failed", "completed"]


@pytest.mark.unit
@pytest.mark.parametrize("cancel_task", [False, True])
async def test_close_and_task_cancel_settle_actual_http_attempt(monkeypatch, cancel_task):
    import httpx
    import litellm

    recorder, store = _recorder()
    closed = asyncio.Event()

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield _sse(None).content.split(b"data: [DONE]")[0]
            await asyncio.Event().wait()

        async def aclose(self):
            closed.set()

    async def send(request):
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, stream=Stream())

    _install_transport(monkeypatch, send)
    stream = recorded_completion_stream_v2(
        litellm.acompletion,
        {
            "model": "openai/gpt-4o",
            "api_key": "private-key",
            "stream": True,
            "messages": [{"role": "user", "content": "hi"}],
        },
        recorder,
    )
    async with aclosing(stream):
        await anext(stream)
        if cancel_task:
            task = asyncio.create_task(anext(stream))
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
    assert closed.is_set()
    assert store.records[-1].event_data["status"] == "cancelled"


@pytest.mark.unit
async def test_legacy_or_absent_snapshot_is_explicitly_missing():
    from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

    recorder, _store = _recorder()
    for legacy in [False, True]:
        if legacy:
            await recorder.append(
                MODEL_REQUEST_PREPARED_EVENT_V2,
                {
                    "attempt_id": "old",
                    "format": "litellm.completion/v1",
                    "request": {"model": "old"},
                },
            )
        with pytest.raises(RuntimeV2Error) as error:
            await replay_prepared_model_request_v2(
                recorder.log, conversation_id="session", message_id="message", attempt_id="old"
            )
        assert error.value.code == "model_request_snapshot_missing"


@pytest.mark.unit
@pytest.mark.parametrize("injected", [False, True])
async def test_real_stream_records_after_guidance_and_context_protocol_transform(
    monkeypatch, injected
):
    recorder, store = _recorder()
    sent = []

    async def send(request):
        sent.append(json.loads(request.content))
        return _sse(None)

    _install_transport(monkeypatch, send)
    messages = [
        {"role": "user", "content": "old context"},
        {"role": "tool", "tool_call_id": "orphan", "content": "orphan result"},
        {"role": "user", "content": "new context"},
        {"role": "system", "content": "[Runtime Guidance] pinned generation"},
    ]
    client = None
    if injected:
        config = ProviderConfig(
            id=uuid4(),
            name="test",
            provider_type=ProviderType.OPENAI,
            api_key_encrypted="unused",
            llm_model="gpt-4o",
            llm_small_model="gpt-4o-mini",
            embedding_model="text-embedding-3-small",
            config={},
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
            client = LiteLLMClient(
                config=LLMConfig(api_key="private-key", model="gpt-4o", temperature=0),
                provider_config=config,
                cache=False,
            )
        monkeypatch.setattr(
            client, "_trim_messages_to_input_limit", lambda *args, **kwargs: messages[1:]
        )

    class Limiter:
        async def acquire(self, provider):
            class Slot:
                async def __aenter__(self):
                    return self

                async def __aexit__(self, *args):
                    pass

            return Slot()

    with patch(
        "src.infrastructure.llm.resilience.get_provider_rate_limiter", return_value=Limiter()
    ):
        stream = LLMStream(
            StreamConfig(
                model="openai/gpt-4o",
                api_key="private-key",
                max_tokens=1000,
                provider_options={"__omit_temperature": True},
            ),
            llm_client=client,
            request_recorder=recorder,
        )
        async for _ in stream.generate(messages if injected else messages[2:]):
            pass
    assert sent and sent[0] == store.records[0].event_data["request"]
    assert sent[0]["messages"] == messages[2:]
    assert sent[0]["model"] == "gpt-4o"
    assert "temperature" not in sent[0]
    assert store.records[-1].event_data["status"] == "completed"
