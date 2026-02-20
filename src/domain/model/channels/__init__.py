"""Channels domain model."""

from src.domain.model.channels.message import (
    Message,
    MessageContent,
    MessageType,
    SenderInfo,
    ChatType,
    ChannelConfig,
    ChannelAdapter,
    MessageReceivedEvent,
    MessageSentEvent,
    ChannelConnectedEvent,
    ChannelDisconnectedEvent,
    ChannelErrorEvent,
)

__all__ = [
    "Message",
    "MessageContent",
    "MessageType",
    "SenderInfo",
    "ChatType",
    "ChannelConfig",
    "ChannelAdapter",
    "MessageReceivedEvent",
    "MessageSentEvent",
    "ChannelConnectedEvent",
    "ChannelDisconnectedEvent",
    "ChannelErrorEvent",
]
