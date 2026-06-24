"""Tests for Redis DLQ adapter logging behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as redis

from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DLQMessageStatus,
    DLQRetryError,
)
from src.infrastructure.adapters.secondary.messaging.redis_dlq import RedisDLQAdapter


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
