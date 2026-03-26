"""Abstract base class for workspace communication channel plugins."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChannelMessage:
    """A message received from or sent to an external channel."""

    channel_type: str
    channel_id: str
    sender_id: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ChannelConfig:
    """Configuration for a workspace channel instance."""

    channel_type: str
    workspace_id: str
    config: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


class WorkspaceChannelPlugin(ABC):
    """Abstract base for workspace communication channel plugins.

    Subclass this to integrate external messaging platforms
    (Slack, DingTalk, Feishu, etc.) with workspace conversations.
    """

    @property
    @abstractmethod
    def channel_type(self) -> str:
        """Unique identifier for this channel type."""
        ...

    @property
    @abstractmethod
    def display_name(self) -> str:
        """Human-readable name for UI display."""
        ...

    @abstractmethod
    async def connect(self, config: ChannelConfig) -> None:
        """Establish connection to the external channel."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully disconnect from the external channel."""
        ...

    @abstractmethod
    async def send_message(
        self,
        channel_id: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Send a message to the external channel."""
        ...

    @abstractmethod
    async def on_message(self, message: ChannelMessage) -> None:
        """Handle an incoming message from the external channel."""
        ...

    async def health_check(self) -> bool:
        """Check if the channel connection is healthy."""
        return True

    def get_config_schema(self) -> dict[str, Any]:
        """Return JSON schema for channel configuration."""
        return {}
