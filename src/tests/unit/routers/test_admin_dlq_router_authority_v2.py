"""Behavior and authority wiring for the generation-owned admin DLQ handlers."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from src.domain.ports.services.dead_letter_queue_port import (
    DeadLetterMessage,
    DLQMessageNotFoundError,
    DLQMessageStatus,
    DLQStats,
)
from src.infrastructure.adapters.primary.web.admin_dlq_application_authority_v2 import (
    AdminDlqApplicationAuthorityV2,
)
from src.infrastructure.adapters.primary.web.routers import admin_dlq as subject

pytestmark = pytest.mark.unit


def _authority(queue: Any) -> AdminDlqApplicationAuthorityV2:
    return cast(
        AdminDlqApplicationAuthorityV2,
        SimpleNamespace(services=SimpleNamespace(queue=queue)),
    )


def _message() -> DeadLetterMessage:
    now = datetime(2026, 8, 26, 12, 0, tzinfo=UTC)
    return DeadLetterMessage(
        id="dlq-a",
        event_id="event-a",
        event_type="agent.failed",
        event_data="{}",
        routing_key="agent:conversation-a",
        error="failed",
        error_type="RuntimeError",
        retry_count=1,
        max_retries=3,
        first_failed_at=now,
        last_failed_at=now,
        status=DLQMessageStatus.PENDING,
        metadata={"source": "test"},
    )


def test_all_handlers_require_only_the_generation_owned_authority() -> None:
    for handler in (
        subject.list_messages,
        subject.get_message,
        subject.retry_message,
        subject.retry_messages,
        subject.discard_message,
        subject.discard_messages,
        subject.get_stats,
        subject.cleanup_expired,
        subject.cleanup_resolved,
    ):
        parameters = inspect.signature(handler).parameters
        assert "admin_dlq" in parameters
        assert "dlq" not in parameters
        assert "_user" not in parameters
        if "request" in parameters:
            assert parameters["request"].annotation in {
                subject.RetryRequest,
                subject.DiscardRequest,
            }


async def test_list_get_and_stats_preserve_transport_contracts() -> None:
    message = _message()
    queue = SimpleNamespace(
        get_messages=AsyncMock(return_value=[message]),
        count_messages=AsyncMock(return_value=1),
        get_message=AsyncMock(return_value=message),
        get_stats=AsyncMock(
            return_value=DLQStats(
                total_messages=3,
                pending_count=1,
                retrying_count=1,
                discarded_count=0,
                expired_count=0,
                resolved_count=1,
                oldest_message_age=42.0,
                error_type_counts={"RuntimeError": 3},
                event_type_counts={"agent.failed": 3},
            )
        ),
    )
    authority = _authority(queue)

    listed = await subject.list_messages(
        admin_dlq=authority,
        filter_status="pending",
        event_type="agent.failed",
        error_type="RuntimeError",
        routing_key="agent:*",
        limit=10,
        offset=2,
    )
    fetched = await subject.get_message("dlq-a", admin_dlq=authority)
    stats = await subject.get_stats(admin_dlq=authority)

    assert listed.total == 1
    assert listed.messages[0].id == "dlq-a"
    assert fetched.id == "dlq-a"
    assert stats.total_messages == 3
    assert stats.oldest_message_age_seconds == 42.0
    queue.get_messages.assert_awaited_once_with(
        status=DLQMessageStatus.PENDING,
        event_type="agent.failed",
        error_type="RuntimeError",
        routing_key_pattern="agent:*",
        limit=10,
        offset=2,
    )


async def test_retry_and_discard_preserve_single_and_batch_results() -> None:
    queue = SimpleNamespace(
        retry_message=AsyncMock(return_value=True),
        retry_batch=AsyncMock(return_value={"dlq-a": True, "dlq-b": False}),
        discard_message=AsyncMock(return_value=True),
        discard_batch=AsyncMock(return_value={"dlq-a": False, "dlq-b": True}),
    )
    authority = _authority(queue)

    retried = await subject.retry_message("dlq-a", admin_dlq=authority)
    retried_batch = await subject.retry_messages(
        subject.RetryRequest(message_ids=["dlq-a", "dlq-b"]),
        admin_dlq=authority,
    )
    discarded = await subject.discard_message(
        "dlq-a",
        reason="operator decision",
        admin_dlq=authority,
    )
    discarded_batch = await subject.discard_messages(
        subject.DiscardRequest(
            message_ids=["dlq-a", "dlq-b"],
            reason="operator decision",
        ),
        admin_dlq=authority,
    )

    assert retried == {
        "message_id": "dlq-a",
        "success": True,
        "message": "Retry initiated",
    }
    assert retried_batch.success_count == 1
    assert retried_batch.failure_count == 1
    assert discarded == {
        "message_id": "dlq-a",
        "success": True,
        "message": "Message discarded",
    }
    assert discarded_batch.success_count == 1
    assert discarded_batch.failure_count == 1


async def test_missing_single_message_stays_a_not_found_transport_error() -> None:
    queue = SimpleNamespace(
        retry_message=AsyncMock(side_effect=DLQMessageNotFoundError("dlq-missing")),
        discard_message=AsyncMock(side_effect=DLQMessageNotFoundError("dlq-missing")),
    )
    authority = _authority(queue)

    with pytest.raises(HTTPException) as retry_error:
        await subject.retry_message("dlq-missing", admin_dlq=authority)
    with pytest.raises(HTTPException) as discard_error:
        await subject.discard_message(
            "dlq-missing",
            reason="operator decision",
            admin_dlq=authority,
        )

    assert retry_error.value.status_code == 404
    assert discard_error.value.status_code == 404


async def test_cleanup_uses_explicit_protocol_hours() -> None:
    queue = SimpleNamespace(
        cleanup_expired=AsyncMock(return_value=4),
        cleanup_resolved=AsyncMock(return_value=2),
    )
    authority = _authority(queue)

    expired = await subject.cleanup_expired(older_than_hours=168, admin_dlq=authority)
    resolved = await subject.cleanup_resolved(older_than_hours=24, admin_dlq=authority)

    assert expired.cleaned_count == 4
    assert resolved.cleaned_count == 2
    queue.cleanup_expired.assert_awaited_once_with(168)
    queue.cleanup_resolved.assert_awaited_once_with(24)
