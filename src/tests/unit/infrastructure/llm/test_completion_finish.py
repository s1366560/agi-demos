"""Provider termination facts never authorize incomplete answers or tool calls."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from src.domain.llm_providers.llm_types import LLMConfig, Message
from src.domain.llm_providers.models import ProviderConfig, ProviderType
from src.infrastructure.agent.core.llm_stream import LLMStream, StreamConfig, StreamEventType
from src.infrastructure.agent.llm.invoker import InvocationConfig, InvocationContext, LLMInvoker
from src.infrastructure.agent.processor.processor import ProcessorConfig, SessionProcessor
from src.infrastructure.agent.retry.policy import RetryPolicy
from src.infrastructure.llm.failover_chain import is_failover_worthy
from src.infrastructure.llm.litellm.litellm_client import LiteLLMClient

pytestmark = pytest.mark.unit


@pytest.fixture
def client() -> LiteLLMClient:
    provider = ProviderConfig(
        id=uuid4(),
        name="completion-fixture",
        provider_type=ProviderType.OPENAI,
        api_key_encrypted="fixture-encrypted",
        llm_model="fixture-model",
        config={},
        is_active=True,
        is_default=False,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    with patch("src.infrastructure.llm.litellm.litellm_client.get_encryption_service"):
        return LiteLLMClient(
            config=LLMConfig(api_key="owned-secret", model="fixture-model"),
            provider_config=provider,
            cache=False,
        )


def chunk(*, content=None, calls=None, reason=None, delta=True) -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                delta=SimpleNamespace(content=content, tool_calls=calls) if delta else None,
                finish_reason=reason,
            )
        ],
        usage=None,
    )


def assert_bounded(error: BaseException, reason: str) -> None:
    assert f"finish_reason={reason}" in str(error)
    assert len(str(error)) < 160
    assert "owned-secret" not in str(error)
    assert RetryPolicy().is_retryable(error) is False
    assert is_failover_worthy(error) is False


@pytest.mark.parametrize("reason", ["length", "content_filter"])
@pytest.mark.parametrize("delta", [False, True])
async def test_terminal_reason_precedes_delta_and_tool_finalization(reason, delta) -> None:
    stream = LLMStream(StreamConfig(model="fixture-model"))
    calls = [
        SimpleNamespace(
            index=0,
            id="fixture-call",
            function=SimpleNamespace(name="fixture", arguments='{"neutral":true}'),
        )
    ]
    first = [event async for event in stream._process_chunk(chunk(calls=calls))]
    assert not any(event.type == StreamEventType.TOOL_CALL_END for event in first)
    with pytest.raises(ValueError) as error:
        [
            event
            async for event in stream._process_chunk(
                chunk(content="owned-secret", calls=calls, reason=reason, delta=delta)
            )
        ]
    assert_bounded(error.value, reason)
    with pytest.raises(ValueError):
        [event async for event in stream._finalize()]
    assert stream._tool_calls[0].complete is False


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_stream_keeps_prefix_and_emits_one_fixed_error_without_retry(reason, caplog) -> None:
    calls = 0
    closed = False

    class Client:
        async def generate_stream(self, **_kwargs) -> AsyncIterator[SimpleNamespace]:
            nonlocal calls, closed
            calls += 1
            try:
                yield chunk(content="neutral prefix")
                yield chunk(content="owned-secret", reason=reason, delta=False)
                raise AssertionError("a rejected terminal must close its source")
            finally:
                closed = True

    stream = LLMStream(StreamConfig(model="fixture-model"), llm_client=Client())
    events = [event async for event in stream.generate([{"role": "user", "content": "neutral"}])]
    assert calls == 1
    assert closed is True
    assert (
        "".join(event.data["delta"] for event in events if event.type == StreamEventType.TEXT_DELTA)
        == "neutral prefix"
    )
    errors = [event for event in events if event.type == StreamEventType.ERROR]
    assert len(errors) == 1
    assert errors[0].data["code"] == (
        "provider_response_incomplete" if reason == "length" else "provider_response_filtered"
    )
    assert f"finish_reason={reason}" in errors[0].data["message"]
    assert "owned-secret" not in errors[0].data["message"] + caplog.text
    assert not any(
        event.type
        in {StreamEventType.TEXT_END, StreamEventType.FINISH, StreamEventType.TOOL_CALL_END}
        for event in events
    )


@pytest.mark.parametrize("reason", [None, "stop", "tool_calls", "provider-specific"])
async def test_stream_accepts_legacy_reasons_and_empty_usage_choices(reason) -> None:
    stream = LLMStream(StreamConfig(model="fixture-model"))
    events = [event async for event in stream._process_chunk(chunk(content="neutral"))]
    events += [event async for event in stream._process_chunk(chunk(reason=reason, delta=False))]
    events += [
        event async for event in stream._process_chunk(SimpleNamespace(choices=[], usage=None))
    ]
    events += [event async for event in stream._finalize()]
    assert events[-1].type == StreamEventType.FINISH
    assert events[-1].data["reason"] == (reason or "stop")


@pytest.mark.parametrize("reason", ["length", "content_filter"])
@pytest.mark.parametrize("method", ["generate", "_generate_response"])
async def test_ordinary_rejects_reason_before_content_or_valid_tool_json(
    client, reason, method, caplog
) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message={
                    "content": None if reason == "content_filter" else "owned-secret",
                    "tool_calls": [
                        {"function": {"name": "fixture", "arguments": '{"neutral":true}'}}
                    ],
                },
                finish_reason=reason,
            )
        ]
    )
    with (
        patch.object(
            client, "_execute_with_resilience", new=AsyncMock(return_value=response)
        ) as call,
        pytest.raises(ValueError) as error,
    ):
        await getattr(client, method)([Message(role="user", content="neutral")])
    assert_bounded(error.value, reason)
    assert call.await_count == 1
    assert "owned-secret" not in caplog.text


@pytest.mark.parametrize("reason", [None, "stop", "provider-specific"])
async def test_ordinary_preserves_first_choice_and_legacy_reason(client, reason) -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(message={"content": "neutral"}, finish_reason=reason),
            SimpleNamespace(message={"content": None}, finish_reason="length"),
        ]
    )
    with patch.object(client, "_execute_with_resilience", new=AsyncMock(return_value=response)):
        result = await client.generate([Message(role="user", content="neutral")])
    assert result["content"] == "neutral"
    assert result["finish_reason"] == reason


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_sdk_stream_rejects_terminal_and_closes_without_retry(client, reason) -> None:
    closed = False

    async def source() -> AsyncIterator[SimpleNamespace]:
        nonlocal closed
        try:
            yield chunk(content="neutral prefix")
            yield chunk(reason=reason, delta=False)
            raise AssertionError("a rejected completion must close its source")
        finally:
            closed = True

    limiter = MagicMock()
    limiter.acquire = AsyncMock()
    breaker = MagicMock()
    breaker.can_execute.return_value = True
    registry = MagicMock()
    registry.get.return_value = breaker
    received = []
    with (
        patch(
            "src.infrastructure.llm.litellm.litellm_client.get_provider_rate_limiter",
            return_value=limiter,
        ),
        patch(
            "src.infrastructure.llm.litellm.litellm_client.get_circuit_breaker_registry",
            return_value=registry,
        ),
        patch("litellm.acompletion", new=AsyncMock(return_value=source())) as call,
        pytest.raises(ValueError) as error,
    ):
        async for value in client.generate_stream([Message(role="user", content="neutral")]):
            received.append(value)
    assert_bounded(error.value, reason)
    assert len(received) == 1
    assert received[0].choices[0].delta.content == "neutral prefix"
    assert closed is True
    assert call.await_count == 1
    breaker.record_failure.assert_not_called()


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_invoker_never_accepts_or_retries_an_incomplete_stream(reason) -> None:
    calls = 0

    class Client:
        async def generate_stream(self, **_kwargs) -> AsyncIterator[SimpleNamespace]:
            nonlocal calls
            calls += 1
            yield chunk(content="neutral prefix")
            yield chunk(reason=reason, delta=False)

    retry = MagicMock()
    retry.is_retryable.return_value = True
    invoker = LLMInvoker(retry_policy=retry, cost_tracker=MagicMock(), failover_chain=MagicMock())
    message = MagicMock()

    async def execute(*_args):
        raise AssertionError("an incomplete response cannot authorize a tool")
        yield

    with pytest.raises(ValueError) as error:
        [
            event
            async for event in invoker.invoke(
                config=InvocationConfig(
                    model="fixture-model", api_key="fixture", llm_client=Client()
                ),
                messages=[{"role": "user", "content": "neutral"}],
                tools={},
                context=InvocationContext(step_count=1),
                current_message=message,
                pending_tool_calls={},
                work_plan_steps=[],
                tool_to_step_mapping={},
                execute_tool_callback=execute,
            )
        ]
    assert_bounded(error.value, reason)
    assert calls == 1
    retry.is_retryable.assert_not_called()


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_processor_does_not_retry_or_complete_a_rejected_response(reason) -> None:
    calls = 0

    class Client:
        async def generate_stream(self, **_kwargs) -> AsyncIterator[SimpleNamespace]:
            nonlocal calls
            calls += 1
            yield chunk(content="neutral prefix")
            yield chunk(reason=reason, delta=False)

    processor = SessionProcessor(config=ProcessorConfig(model="fixture-model"), tools=[])
    processor._llm_client = Client()
    with pytest.raises(Exception, match=f"finish_reason={reason}"):
        [
            event
            async for event in processor._process_step(
                "fixture-session", [{"role": "user", "content": "neutral"}]
            )
        ]
    assert calls == 1


@pytest.mark.parametrize("reason", ["length", "content_filter"])
async def test_cached_incomplete_completion_cannot_bypass_the_guard(client, reason) -> None:
    client.cache = True
    cache = MagicMock()
    cache.get = AsyncMock(return_value={"content": "owned-secret", "finish_reason": reason})
    with (
        patch("src.infrastructure.llm.cache.get_response_cache", return_value=cache),
        patch.object(client, "_execute_with_resilience", new=AsyncMock()) as call,
        pytest.raises(ValueError) as error,
    ):
        await client.generate([Message(role="user", content="neutral")])
    assert_bounded(error.value, reason)
    call.assert_not_awaited()
