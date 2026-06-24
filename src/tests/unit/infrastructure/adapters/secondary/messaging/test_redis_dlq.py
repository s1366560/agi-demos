"""Tests for Redis DLQ adapter logging behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as redis

from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DLQError,
    DLQMessageStatus,
    DLQRetryError,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_to_dlq_redacts_store_failure_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """DLQ store failures should not log raw Redis exception text."""
    exception_detail = "store failed redis secret 4826"

    class _FailingPipeline:
        async def __aenter__(self) -> "_FailingPipeline":
            return self

        async def __aexit__(
            self,
            _exc_type: type[BaseException] | None,
            _exc: BaseException | None,
            _traceback: object | None,
        ) -> None:
            return None

        def hset(self, *_args: object, **_kwargs: object) -> None:
            return None

        def expire(self, *_args: object, **_kwargs: object) -> None:
            return None

        def zadd(self, *_args: object, **_kwargs: object) -> None:
            return None

        def hincrby(self, *_args: object, **_kwargs: object) -> None:
            return None

        async def execute(self) -> None:
            raise redis.RedisError(exception_detail)

    redis_client = SimpleNamespace(pipeline=lambda transaction=True: _FailingPipeline())
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with (
        caplog.at_level(
            "ERROR",
            logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
        ),
        pytest.raises(DLQError) as exc_info,
    ):
        await adapter.send_to_dlq(
            event_id="event-secret-4826",
            event_type="event.type",
            event_data="{}",
            routing_key="routing.secret",
            error="original error",
            error_type="RuntimeError",
            retry_count=1,
        )

    assert exception_detail in str(exc_info.value)
    assert "Failed to store message" in caplog.text
    assert exception_detail not in caplog.text
    assert "event-secret-4826" not in caplog.text
    assert "routing.secret" not in caplog.text
    assert "redis_error_type=RedisError" in caplog.text
    assert "event_type=event.type" in caplog.text
    assert "dlq_error_type=RuntimeError" in caplog.text
    assert "retry_count=1" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_message_redacts_publish_failure_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry publish failures should not log raw exception text or message IDs."""
    exception_detail = "publish failed dlq-secret-1357"
    secret_message_id = "dlq-secret-message-2468"

    class _FailingEventBus:
        @staticmethod
        async def publish(_envelope: object, _routing_key: str) -> None:
            raise RuntimeError(exception_detail)

    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
        retry_count=0,
        max_retries=3,
    )
    adapter = RedisDLQAdapter(redis_client=object(), event_bus=_FailingEventBus())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "src.infrastructure.adapters.secondary.messaging.redis_dlq.EventEnvelope.from_json",
            return_value=SimpleNamespace(event_id="event-1"),
        ),
        caplog.at_level(
            "WARNING",
            logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
        ),
    ):
        retried = await adapter.retry_message(secret_message_id)

    assert retried is False
    assert "Retry failed" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_message_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_message_id=True" in caplog.text
    assert message.error == exception_detail
    assert message.error_traceback is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_message_success_redacts_message_id_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful retry logs should not include raw message IDs."""
    secret_message_id = "dlq-secret-message-3141"

    class _SuccessfulEventBus:
        publish = AsyncMock()

    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
        retry_count=0,
        max_retries=3,
    )
    adapter = RedisDLQAdapter(redis_client=object(), event_bus=_SuccessfulEventBus())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock()  # type: ignore[method-assign]
    adapter._update_stats_on_resolve = AsyncMock()  # type: ignore[method-assign]

    with (
        patch(
            "src.infrastructure.adapters.secondary.messaging.redis_dlq.EventEnvelope.from_json",
            return_value=SimpleNamespace(event_id="event-1"),
        ),
        caplog.at_level(
            "INFO",
            logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
        ),
    ):
        retried = await adapter.retry_message(secret_message_id)

    assert retried is True
    assert message.status == DLQMessageStatus.RESOLVED
    assert adapter._update_message.await_count == 2  # type: ignore[attr-defined]
    adapter._update_stats_on_resolve.assert_awaited_once_with(message)  # type: ignore[attr-defined]
    assert "Message retried successfully" in caplog.text
    assert secret_message_id not in caplog.text
    assert "has_message_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_message_without_event_bus_redacts_message_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing event bus retry warnings should not log raw message IDs."""
    secret_message_id = "dlq-secret-message-6420"
    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
        retry_count=0,
        max_retries=3,
    )
    adapter = RedisDLQAdapter(redis_client=object())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock()  # type: ignore[method-assign]

    with caplog.at_level(
        "WARNING",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        retried = await adapter.retry_message(secret_message_id)

    assert retried is False
    assert "Cannot retry" in caplog.text
    assert secret_message_id not in caplog.text
    assert "reason=no_event_bus" in caplog.text
    assert "has_message_id=True" in caplog.text
    assert message.status == DLQMessageStatus.PENDING


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_message_redacts_outer_update_failure_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry setup failures should not log raw exception text or message IDs."""
    exception_detail = "update failed dlq-secret-2601"
    secret_message_id = "dlq-secret-message-3712"
    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
        retry_count=0,
        max_retries=3,
    )
    adapter = RedisDLQAdapter(redis_client=object())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock(side_effect=RuntimeError(exception_detail))  # type: ignore[method-assign]

    with (
        caplog.at_level(
            "ERROR",
            logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
        ),
        pytest.raises(DLQRetryError) as exc_info,
    ):
        await adapter.retry_message(secret_message_id)

    assert exc_info.value.message_id == secret_message_id
    assert exc_info.value.reason == exception_detail
    assert "Error retrying" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_message_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_message_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_batch_redacts_retry_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Batch retry failures should not log raw exception text or message IDs."""
    exception_detail = "batch failed dlq-secret-8642"
    secret_message_id = "dlq-secret-message-9753"

    adapter = RedisDLQAdapter(redis_client=object())  # type: ignore[arg-type]
    adapter.retry_message = AsyncMock(  # type: ignore[method-assign]
        side_effect=DLQRetryError(secret_message_id, exception_detail)
    )

    with caplog.at_level(
        "WARNING",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        results = await adapter.retry_batch([secret_message_id])

    assert results == {secret_message_id: False}
    assert "Batch retry failed" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_message_id not in caplog.text
    assert "error_type=DLQRetryError" in caplog.text
    assert "has_message_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discard_message_redacts_update_failure_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Discard failures should not log raw exception text or message IDs."""
    exception_detail = "discard failed dlq-secret-5319"
    secret_message_id = "dlq-secret-message-7531"

    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
    )
    adapter = RedisDLQAdapter(redis_client=object())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock(side_effect=RuntimeError(exception_detail))  # type: ignore[method-assign]
    adapter._update_stats_on_discard = AsyncMock()  # type: ignore[method-assign]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        discarded = await adapter.discard_message(secret_message_id, "operator-secret")

    assert discarded is False
    assert "Error discarding" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_message_id not in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_message_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_discard_message_success_redacts_reason_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful discard logs should not include raw message IDs or reasons."""
    secret_message_id = "dlq-secret-message-8640"
    secret_reason = "operator pasted secret token 9753"

    message = DeadLetterMessage(
        id=secret_message_id,
        event_id="event-1",
        event_type="event.type",
        event_data="{}",
        routing_key="routing.secret",
        error="original error",
        error_type="RuntimeError",
        status=DLQMessageStatus.PENDING,
    )
    adapter = RedisDLQAdapter(redis_client=object())  # type: ignore[arg-type]
    adapter.get_message = AsyncMock(return_value=message)  # type: ignore[method-assign]
    adapter._update_message = AsyncMock()  # type: ignore[method-assign]
    adapter._update_stats_on_discard = AsyncMock()  # type: ignore[method-assign]

    with caplog.at_level(
        "INFO",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        discarded = await adapter.discard_message(secret_message_id, secret_reason)

    assert discarded is True
    assert message.status == DLQMessageStatus.DISCARDED
    assert message.metadata["discard_reason"] == secret_reason
    assert "discarded_at" in message.metadata
    assert "Message discarded" in caplog.text
    assert secret_message_id not in caplog.text
    assert secret_reason not in caplog.text
    assert "has_message_id=True" in caplog.text
    assert "has_reason=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_message_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Single-message fetch failures should not log raw exception text or message IDs."""
    exception_detail = "fetch redis secret 0369"
    secret_message_id = "dlq-secret-message-1590"
    redis_client = SimpleNamespace(
        hget=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        message = await adapter.get_message(secret_message_id)

    assert message is None
    assert "Failed to get message" in caplog.text
    assert exception_detail not in caplog.text
    assert secret_message_id not in caplog.text
    assert "error_type=RedisError" in caplog.text
    assert "has_message_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_messages_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Message query failures should not log raw Redis exception text."""
    exception_detail = "query redis secret 1472"
    redis_client = SimpleNamespace(
        zrevrange=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        messages = await adapter.get_messages(limit=5, offset=2)

    assert messages == []
    assert "Failed to get messages" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RedisError" in caplog.text
    assert "limit=5" in caplog.text
    assert "offset=2" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_count_messages_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Message count failures should not log raw Redis exception text."""
    exception_detail = "count redis secret 2583"
    redis_client = SimpleNamespace(
        zrevrange=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        count = await adapter.count_messages()

    assert count == 0
    assert "Failed to count messages" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RedisError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_stats_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Stats failures should not log raw Redis exception text."""
    exception_detail = "stats redis secret 7241"
    redis_client = SimpleNamespace(
        hgetall=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        stats = await adapter.get_stats()

    assert stats.total_messages == 0
    assert "Failed to get stats" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RedisError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_expired_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Expired cleanup failures should not log raw Redis exception text."""
    exception_detail = "expired cleanup redis secret 8352"
    redis_client = SimpleNamespace(
        zrangebyscore=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        cleaned = await adapter.cleanup_expired(older_than_hours=42)

    assert cleaned == 0
    assert "Cleanup failed" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RedisError" in caplog.text
    assert "older_than_hours=42" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_cleanup_resolved_redacts_redis_error_log(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Resolved cleanup failures should not log raw Redis exception text."""
    exception_detail = "resolved cleanup redis secret 9463"
    redis_client = SimpleNamespace(
        zrangebyscore=AsyncMock(side_effect=redis.RedisError(exception_detail)),
    )
    adapter = RedisDLQAdapter(redis_client=redis_client)  # type: ignore[arg-type]

    with caplog.at_level(
        "ERROR",
        logger="src.infrastructure.adapters.secondary.messaging.redis_dlq",
    ):
        cleaned = await adapter.cleanup_resolved(older_than_hours=13)

    assert cleaned == 0
    assert "Resolved cleanup failed" in caplog.text
    assert exception_detail not in caplog.text
    assert "error_type=RedisError" in caplog.text
    assert "older_than_hours=13" in caplog.text
