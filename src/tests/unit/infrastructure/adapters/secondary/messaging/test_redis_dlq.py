"""Tests for Redis DLQ adapter logging behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

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
