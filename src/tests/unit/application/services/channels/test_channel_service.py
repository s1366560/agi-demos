"""Unit tests for ChannelService."""

import logging

import pytest

from src.application.services.channels.channel_service import ChannelService
from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)


def _build_message(text: str) -> Message:
    return Message(
        channel="feishu",
        chat_type=ChatType.P2P,
        chat_id="chat-1",
        sender=SenderInfo(id="sender-1", name="Test User"),
        content=MessageContent(type=MessageType.TEXT, text=text),
        project_id="project-1",
    )


@pytest.mark.unit
def test_handle_message_log_omits_message_text(caplog: pytest.LogCaptureFixture) -> None:
    """Inbound channel logs should not expose message text."""
    service = ChannelService()
    message = _build_message("secret launch plan: private-roadmap.pdf")
    caplog.set_level(
        logging.DEBUG,
        logger="src.application.services.channels.channel_service",
    )

    service._handle_message(message)

    assert "secret launch plan" not in caplog.text
    assert "private-roadmap.pdf" not in caplog.text
    assert "has_text=True" in caplog.text


@pytest.mark.unit
def test_handle_message_handler_failure_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Message handler failure logs should not expose exception details."""
    service = ChannelService()
    message = _build_message("hello")

    def failing_handler(_: Message) -> None:
        raise RuntimeError("secret-handler-token")

    service.on_message(failing_handler)
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    service._handle_message(message)

    assert "secret-handler-token" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.unit
def test_handle_error_log_omits_channel_id_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Channel error logs should not expose channel IDs or exception details."""
    service = ChannelService()
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    service._handle_error("secret-channel-id", RuntimeError("secret-channel-token"))

    assert "secret-channel-id" not in caplog.text
    assert "secret-channel-token" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
def test_handle_error_handler_failure_log_omits_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Error handler failure logs should not expose exception details."""
    service = ChannelService()

    def failing_handler(_: str, __: Exception) -> None:
        raise RuntimeError("secret-error-handler-token")

    service.on_error(failing_handler)
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    service._handle_error("secret-channel-id", RuntimeError("secret-channel-token"))

    assert "secret-error-handler-token" not in caplog.text
    assert "RuntimeError" in caplog.text
