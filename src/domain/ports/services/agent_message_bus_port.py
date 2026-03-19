"""
Agent Message Bus Port - Abstract interface for inter-agent messaging.

This port defines the contract for agent-to-agent communication,
enabling reliable message delivery between agent sessions.

The abstraction allows switching between different message bus implementations:
- Redis Streams (default, recommended)
- Kafka
- RabbitMQ
- etc.

Key Features:
- Per-session message streams
- Polling and blocking subscription modes
- Message threading via parent_message_id
- Session-level cleanup
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class AgentMessageType(str, Enum):
    """Type of inter-agent message."""

    REQUEST = "request"  # Request from one agent to another
    RESPONSE = "response"  # Response to a prior request
    NOTIFICATION = "notification"  # One-way notification (no reply expected)
    ANNOUNCE = "announce"  # Child-to-parent completion announcement


@dataclass
class AgentMessage:
    """
    A message in the inter-agent message bus.

    Attributes:
        message_id: Unique message ID (assigned by the bus)
        from_agent_id: ID of the sending agent
        to_agent_id: ID of the target agent
        session_id: Target agent session ID
        content: Message content (text)
        message_type: Type of message (request, response, notification)
        timestamp: When the message was created
        metadata: Additional metadata
        parent_message_id: ID of the parent message (for threading)
    """

    message_id: str
    from_agent_id: str
    to_agent_id: str
    session_id: str
    content: str
    message_type: AgentMessageType
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None
    parent_message_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "message_id": self.message_id,
            "from_agent_id": self.from_agent_id,
            "to_agent_id": self.to_agent_id,
            "session_id": self.session_id,
            "content": self.content,
            "message_type": self.message_type.value,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {},
            "parent_message_id": self.parent_message_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentMessage:
        """Create from dictionary."""
        return cls(
            message_id=data.get("message_id", ""),
            from_agent_id=data.get("from_agent_id", ""),
            to_agent_id=data.get("to_agent_id", ""),
            session_id=data.get("session_id", ""),
            content=data.get("content", ""),
            message_type=AgentMessageType(data.get("message_type", "notification")),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else data.get("timestamp", datetime.now(UTC))
            ),
            metadata=data.get("metadata"),
            parent_message_id=data.get("parent_message_id"),
        )


class AgentMessageBusPort(ABC):
    """
    Abstract port for inter-agent messaging.

    This port provides message delivery between agent sessions:
    - Agent A can send a message to Agent B's session stream
    - Agent B can poll or subscribe to its session stream for incoming messages

    Implementation Requirements:
    - Messages must persist until the session is cleaned up
    - One stream per target agent session
    - Implementations should handle reconnection gracefully
    - Sessions should be cleaned up when no longer needed
    """

    @abstractmethod
    async def send_message(
        self,
        from_agent_id: str,
        to_agent_id: str,
        session_id: str,
        content: str,
        message_type: AgentMessageType,
        metadata: dict[str, Any] | None = None,
        parent_message_id: str | None = None,
    ) -> str:
        """
        Send a message to an agent's session stream.

        This is called when one agent wants to communicate with another.
        The message is appended to the target session's stream.

        Args:
            from_agent_id: ID of the sending agent
            to_agent_id: ID of the target agent
            session_id: Target agent session ID
            content: Message content
            message_type: Type of message (request, response, notification)
            metadata: Optional additional metadata
            parent_message_id: Optional parent message ID for threading

        Returns:
            Message ID assigned by the bus
        """

    @abstractmethod
    async def receive_messages(
        self,
        agent_id: str,
        session_id: str,
        since_id: str | None = None,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """
        Poll for new messages in an agent's session stream (non-blocking).

        Reads messages from the session stream, optionally starting after
        a given message ID.

        Args:
            agent_id: ID of the receiving agent
            session_id: Session ID to read from
            since_id: Only return messages after this ID (exclusive)
            limit: Maximum number of messages to return

        Returns:
            List of messages in chronological order
        """

    @abstractmethod
    async def subscribe_messages(
        self,
        agent_id: str,
        session_id: str,
        timeout_ms: int = 5000,
    ) -> AsyncIterator[AgentMessage]:
        """
        Subscribe to messages in an agent's session stream (blocking).

        Blocks until new messages arrive or timeout is reached.
        Yields messages as they arrive.

        Args:
            agent_id: ID of the receiving agent
            session_id: Session ID to subscribe to
            timeout_ms: Block timeout in milliseconds

        Yields:
            AgentMessage objects as they arrive
        """

    @abstractmethod
    async def get_message_history(
        self,
        session_id: str,
        limit: int = 50,
    ) -> list[AgentMessage]:
        """
        Get message history for a session.

        Returns the most recent messages from the session stream.

        Args:
            session_id: Session ID to get history for
            limit: Maximum number of messages to return

        Returns:
            List of messages in chronological order
        """

    @abstractmethod
    async def cleanup_session(self, session_id: str) -> None:
        """
        Delete a session's message stream.

        Called when a session is no longer needed to free resources.

        Args:
            session_id: Session ID to clean up
        """

    @abstractmethod
    async def session_has_messages(self, session_id: str) -> bool:
        """
        Check if any messages exist in a session's stream.

        Args:
            session_id: Session ID to check

        Returns:
            True if the session stream exists and has messages
        """
