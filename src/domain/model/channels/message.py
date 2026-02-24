"""Channels domain model - Message entities and value objects."""

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Protocol

from src.domain.shared_kernel import DomainEvent, Entity, ValueObject


class MessageType(str, Enum):
    """Message content types."""

    TEXT = "text"
    IMAGE = "image"
    FILE = "file"
    AUDIO = "audio"
    VIDEO = "video"
    CARD = "card"
    POST = "post"
    STICKER = "sticker"


class ChatType(str, Enum):
    """Chat types."""

    P2P = "p2p"
    GROUP = "group"


@dataclass(frozen=True)
class MessageContent(ValueObject):
    """Message content value object."""

    type: MessageType
    text: str | None = None
    image_key: str | None = None
    file_key: str | None = None
    file_name: str | None = None
    card: dict[str, Any] | None = None
    # Media metadata fields
    duration: int | None = None  # Audio/video duration in seconds
    size: int | None = None  # File size in bytes
    mime_type: str | None = None  # MIME type
    thumbnail_key: str | None = None  # Video thumbnail key
    extra_media_data: dict[str, Any] | None = None  # Additional metadata
    sandbox_path: str | None = None  # Path after import to sandbox
    artifact_id: str | None = None  # Artifact reference

    def is_text(self) -> bool:
        return self.type == MessageType.TEXT

    def is_image(self) -> bool:
        return self.type == MessageType.IMAGE

    def is_media(self) -> bool:
        """Check if message is a media type."""
        return self.type in (
            MessageType.IMAGE,
            MessageType.FILE,
            MessageType.AUDIO,
            MessageType.VIDEO,
            MessageType.STICKER,
        )

    def has_media_to_import(self) -> bool:
        """Check if message has media content to import (including post with images)."""
        return self.is_media() or (self.type == MessageType.POST and self.image_key is not None)

    def generate_display_text(self) -> str:
        """Generate contextual display text for the message."""
        if self.text:
            return self.text

        if self.type == MessageType.IMAGE:
            size_info = f" ({self.size} bytes)" if self.size else ""
            return f"[图片消息{size_info}]"
        elif self.type == MessageType.FILE:
            name = self.file_name or "unknown"
            size_info = f" ({self.size} bytes)" if self.size else ""
            return f"[文件: {name}{size_info}]"
        elif self.type == MessageType.AUDIO:
            duration_info = f"{self.duration}秒" if self.duration else "未知时长"
            return f"[语音消息: {duration_info}]"
        elif self.type == MessageType.VIDEO:
            duration_info = f"{self.duration}秒" if self.duration else "未知时长"
            return f"[视频消息: {duration_info}]"
        elif self.type == MessageType.STICKER:
            return "[表情消息]"
        else:
            return ""


@dataclass(frozen=True)
class SenderInfo(ValueObject):
    """Sender information value object."""

    id: str
    name: str | None = None
    avatar: str | None = None


@dataclass(kw_only=True)
class Message(Entity):
    """Message entity representing a unified message across all channels."""

    channel: str  # e.g., 'feishu', 'dingtalk', 'wecom'
    chat_type: ChatType
    chat_id: str
    sender: SenderInfo
    content: MessageContent
    project_id: str | None = None
    reply_to: str | None = None  # message_id being replied to
    thread_id: str | None = None  # thread/topic identifier
    sender_type: str = "user"  # user, bot, app
    mentions: list[str] = field(default_factory=list)  # mentioned user IDs
    raw_data: dict[str, Any] | None = field(default=None, repr=False)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    @property
    def is_group_message(self) -> bool:
        return self.chat_type == ChatType.GROUP

    @property
    def is_reply(self) -> bool:
        return self.reply_to is not None


@dataclass(frozen=True)
class ChannelConfig(ValueObject):
    """Channel configuration value object."""

    enabled: bool = True
    app_id: str | None = None
    app_secret: str | None = None
    encrypt_key: str | None = None
    verification_token: str | None = None
    connection_mode: str = "websocket"  # websocket or webhook
    webhook_port: int | None = None
    webhook_path: str | None = None
    domain: str | None = None  # feishu, lark, or custom
    extra: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Protocol):
    """Channel adapter interface (Port in Hexagonal Architecture).

    This protocol defines the interface that all channel adapters must implement.
    Adapters are responsible for connecting to specific IM platforms
    (Feishu, DingTalk, WeCom, etc.) and translating between the platform's
    native format and the unified Message format.
    """

    @property
    def id(self) -> str:
        """Unique identifier for this channel (e.g., 'feishu', 'dingtalk')."""
        ...

    @property
    def name(self) -> str:
        """Human-readable name for this channel."""
        ...

    @property
    def connected(self) -> bool:
        """Whether the channel is currently connected."""
        ...

    async def connect(self) -> None:
        """Establish connection to the channel."""
        ...

    async def disconnect(self) -> None:
        """Close connection to the channel."""
        ...

    async def send_message(
        self, to: str, content: MessageContent, reply_to: str | None = None
    ) -> str:
        """Send a message to the specified recipient.

        Args:
            to: Recipient ID (chat_id for groups, user_id for private)
            content: Message content
            reply_to: Optional message ID to reply to

        Returns:
            Sent message ID
        """
        ...

    async def send_text(self, to: str, text: str, reply_to: str | None = None) -> str:
        """Send a text message (convenience method)."""
        ...

    def on_message(self, handler: Callable[[Message], None]) -> Callable[[], None]:
        """Register a message handler callback.

        Returns a function to unregister the handler.
        """
        ...

    def on_error(self, handler: Callable[[Exception], None]) -> Callable[[], None]:
        """Register an error handler callback."""
        ...

    async def get_chat_members(self, chat_id: str) -> list[SenderInfo]:
        """Get members of a chat group."""
        ...

    async def get_user_info(self, user_id: str) -> SenderInfo | None:
        """Get user information by ID."""
        ...

    async def edit_message(self, message_id: str, content: MessageContent) -> bool:
        """Edit a previously sent message."""
        ...

    async def delete_message(self, message_id: str) -> bool:
        """Delete/recall a message."""
        ...

    async def send_card(
        self,
        to: str,
        card: dict[str, Any],
        reply_to: str | None = None,
    ) -> str:
        """Send an interactive card message."""
        ...

    async def health_check(self) -> bool:
        """Verify the connection is alive (e.g. API ping). Returns True if healthy."""
        ...

    async def patch_card(self, message_id: str, card_content: str) -> bool:
        """Update (patch) an existing interactive card message.

        Args:
            message_id: The message_id of the card to update.
            card_content: JSON string of the new card content.

        Returns:
            True on success, False on failure.
        """
        ...

    async def send_markdown_card(
        self,
        to: str,
        markdown: str,
        reply_to: str | None = None,
    ) -> str:
        """Send markdown content as an interactive card."""
        ...


# Domain Events


@dataclass(frozen=True, kw_only=True)
class MessageReceivedEvent(DomainEvent):
    """Event emitted when a message is received from a channel."""

    message: Message


@dataclass(frozen=True, kw_only=True)
class MessageSentEvent(DomainEvent):
    """Event emitted when a message is sent to a channel."""

    channel: str
    message_id: str
    to: str
    content: MessageContent


@dataclass(frozen=True, kw_only=True)
class ChannelConnectedEvent(DomainEvent):
    """Event emitted when a channel connects."""

    channel: str


@dataclass(frozen=True, kw_only=True)
class ChannelDisconnectedEvent(DomainEvent):
    """Event emitted when a channel disconnects."""

    channel: str
    reason: str | None = None


@dataclass(frozen=True, kw_only=True)
class ChannelErrorEvent(DomainEvent):
    """Event emitted when a channel encounters an error."""

    channel: str
    error: str


@dataclass(frozen=True, kw_only=True)
class MessageEditedEvent(DomainEvent):
    """Event emitted when a message is edited in a channel."""

    channel: str
    message_id: str
    new_content: MessageContent


@dataclass(frozen=True, kw_only=True)
class MessageDeletedEvent(DomainEvent):
    """Event emitted when a message is deleted/recalled from a channel."""

    channel: str
    message_id: str
