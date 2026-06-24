"""Unit tests for channel outbox retry worker logging behavior."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.channels.outbox_worker import OutboxRetryWorker


@pytest.mark.unit
@pytest.mark.asyncio
async def test_retry_item_redacts_retry_and_status_update_failures(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Retry failures should not log raw exception text or channel identifiers."""
    retry_exception_detail = "send failed channel-outbox-retry-secret-1357"
    status_exception_detail = "status failed channel-outbox-status-secret-2468"
    secret_outbox_id = "outbox-secret-9753"
    secret_config_id = "config-secret-8642"

    class _FailingAdapter:
        connected = True

        @staticmethod
        async def send_text(*_args: object, **_kwargs: object) -> str:
            raise ValueError(retry_exception_detail)

    worker = OutboxRetryWorker(
        session_factory=lambda: None,
        get_connection_fn=lambda _config_id: SimpleNamespace(adapter=_FailingAdapter()),
    )
    item = SimpleNamespace(
        id=secret_outbox_id,
        channel_config_id=secret_config_id,
        chat_id="chat-secret-1111",
        content_text="message secret 2222",
        reply_to_channel_message_id=None,
    )
    repo = SimpleNamespace(
        mark_failed=AsyncMock(side_effect=RuntimeError(status_exception_detail)),
    )
    session = SimpleNamespace(commit=AsyncMock())

    with caplog.at_level(
        "WARNING",
        logger="src.infrastructure.channels.outbox_worker",
    ):
        await worker._retry_item(item, repo, session)  # type: ignore[arg-type]

    assert "Failed to update outbox status" in caplog.text
    assert "Retry failed" in caplog.text
    assert retry_exception_detail not in caplog.text
    assert status_exception_detail not in caplog.text
    assert secret_outbox_id not in caplog.text
    assert secret_config_id not in caplog.text
    assert "error_type=ValueError" in caplog.text
    assert "error_type=RuntimeError" in caplog.text
    assert "has_outbox_id=True" in caplog.text
    repo.mark_failed.assert_awaited_once_with(secret_outbox_id, retry_exception_detail)
    session.commit.assert_not_awaited()
