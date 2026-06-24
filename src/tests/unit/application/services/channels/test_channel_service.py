"""Unit tests for ChannelService."""

import logging
from collections.abc import Callable

import pytest

from src.application.services.channels.channel_service import ChannelService
from src.domain.model.channels.message import (
    ChatType,
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
)


class _FailingSendAdapter:
    def __init__(self) -> None:
        self._message_handler: Callable[[Message], None] | None = None
        self._error_handler: Callable[[Exception], None] | None = None

    @property
    def id(self) -> str:
        return "secret-channel-id"

    @property
    def name(self) -> str:
        return "Secret Channel"

    @property
    def connected(self) -> bool:
        return True

    async def connect(self) -> None:
        return None

    async def disconnect(self) -> None:
        return None

    async def send_message(
        self,
        to: str,
        content: MessageContent,
        reply_to: str | None = None,
    ) -> str:
        raise RuntimeError("secret-send-token")

    async def send_text(self, to: str, text: str, reply_to: str | None = None) -> str:
        raise RuntimeError("secret-send-token")

    def on_message(self, handler: Callable[[Message], None]) -> Callable[[], None]:
        self._message_handler = handler

        def unregister() -> None:
            self._message_handler = None

        return unregister

    def on_error(self, handler: Callable[[Exception], None]) -> Callable[[], None]:
        self._error_handler = handler

        def unregister() -> None:
            self._error_handler = None

        return unregister

    async def get_chat_members(self, chat_id: str) -> list[SenderInfo]:
        return []

    async def get_user_info(self, user_id: str) -> SenderInfo | None:
        return None


class _SuccessfulSendAdapter(_FailingSendAdapter):
    async def send_message(
        self,
        to: str,
        content: MessageContent,
        reply_to: str | None = None,
    ) -> str:
        return "secret-message-id"

    async def send_text(self, to: str, text: str, reply_to: str | None = None) -> str:
        return "secret-message-id"


class _DisconnectedSendAdapter(_FailingSendAdapter):
    @property
    def connected(self) -> bool:
        return False


class _FailingConnectAdapter(_FailingSendAdapter):
    async def connect(self) -> None:
        raise RuntimeError("secret-connect-token")


class _FailingDisconnectAdapter(_FailingSendAdapter):
    async def disconnect(self) -> None:
        raise RuntimeError("secret-disconnect-token")


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
def test_register_adapter_log_omits_adapter_name_and_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter registration logs should not expose adapter names or IDs."""
    service = ChannelService()
    caplog.set_level(
        logging.INFO,
        logger="src.application.services.channels.channel_service",
    )

    service.register_adapter(_FailingSendAdapter())

    assert "Secret Channel" not in caplog.text
    assert "secret-channel-id" not in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
def test_unregister_adapter_log_omits_adapter_name_and_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Adapter unregistration logs should not expose adapter names or IDs."""
    service = ChannelService()
    service.register_adapter(_FailingSendAdapter())
    caplog.set_level(
        logging.INFO,
        logger="src.application.services.channels.channel_service",
    )
    caplog.clear()

    service.unregister_adapter("secret-channel-id")

    assert "Secret Channel" not in caplog.text
    assert "secret-channel-id" not in caplog.text
    assert "has_channel_id=True" in caplog.text


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


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_failure_log_omits_channel_id_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Send failure logs should not expose channel IDs or adapter exception details."""
    service = ChannelService()
    service.register_adapter(_FailingSendAdapter())
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    result = await service.send_message(
        "secret-channel-id",
        "secret-recipient-id",
        MessageContent(type=MessageType.TEXT, text="private response body"),
    )

    assert result is None
    assert "secret-channel-id" not in caplog.text
    assert "secret-recipient-id" not in caplog.text
    assert "private response body" not in caplog.text
    assert "secret-send-token" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_broadcast_failure_log_omits_adapter_name_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Broadcast failure logs should not expose adapter names or exception details."""
    service = ChannelService()
    service.register_adapter(_FailingSendAdapter())
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    result = await service.broadcast(
        "secret-recipient-id",
        MessageContent(type=MessageType.TEXT, text="private broadcast body"),
    )

    assert result == {"secret-channel-id": None}
    assert "Secret Channel" not in caplog.text
    assert "secret-recipient-id" not in caplog.text
    assert "private broadcast body" not in caplog.text
    assert "secret-send-token" not in caplog.text
    assert "RuntimeError" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_success_log_omits_channel_and_message_ids(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful send logs should not expose channel IDs, recipients, content, or message IDs."""
    service = ChannelService()
    service.register_adapter(_SuccessfulSendAdapter())
    caplog.set_level(
        logging.DEBUG,
        logger="src.application.services.channels.channel_service",
    )

    result = await service.send_message(
        "secret-channel-id",
        "secret-recipient-id",
        MessageContent(type=MessageType.TEXT, text="private response body"),
    )

    assert result == "secret-message-id"
    assert "secret-channel-id" not in caplog.text
    assert "secret-recipient-id" not in caplog.text
    assert "private response body" not in caplog.text
    assert "secret-message-id" not in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_missing_channel_log_omits_channel_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Missing channel logs should not expose requested channel IDs."""
    service = ChannelService()
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    result = await service.send_message(
        "secret-missing-channel-id",
        "secret-recipient-id",
        MessageContent(type=MessageType.TEXT, text="private response body"),
    )

    assert result is None
    assert "secret-missing-channel-id" not in caplog.text
    assert "secret-recipient-id" not in caplog.text
    assert "private response body" not in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_send_message_disconnected_channel_log_omits_channel_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disconnected channel logs should not expose requested channel IDs."""
    service = ChannelService()
    service.register_adapter(_DisconnectedSendAdapter())
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    result = await service.send_message(
        "secret-channel-id",
        "secret-recipient-id",
        MessageContent(type=MessageType.TEXT, text="private response body"),
    )

    assert result is None
    assert "secret-channel-id" not in caplog.text
    assert "secret-recipient-id" not in caplog.text
    assert "private response body" not in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_connect_all_failure_log_omits_adapter_name_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Connect failure logs should not expose adapter names or exception details."""
    service = ChannelService()
    service.register_adapter(_FailingConnectAdapter())
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    await service.connect_all()

    assert "Secret Channel" not in caplog.text
    assert "secret-channel-id" not in caplog.text
    assert "secret-connect-token" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "has_channel_id=True" in caplog.text


@pytest.mark.unit
@pytest.mark.asyncio
async def test_disconnect_all_failure_log_omits_adapter_name_and_exception_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Disconnect failure logs should not expose adapter names or exception details."""
    service = ChannelService()
    service.register_adapter(_FailingDisconnectAdapter())
    caplog.set_level(
        logging.ERROR,
        logger="src.application.services.channels.channel_service",
    )

    await service.disconnect_all()

    assert "Secret Channel" not in caplog.text
    assert "secret-channel-id" not in caplog.text
    assert "secret-disconnect-token" not in caplog.text
    assert "RuntimeError" in caplog.text
    assert "has_channel_id=True" in caplog.text
