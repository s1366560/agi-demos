"""
HITL Message Bus Port - Abstract interface for Human-in-the-Loop messaging.

This port defines the contract for cross-process HITL communication,
enabling reliable message delivery between API processes and Worker processes.

The abstraction allows switching between different message bus implementations:
- Redis Streams (default, recommended)
- Kafka
- RabbitMQ
- AWS SQS
- etc.

Key Features:
- Message persistence (survives process restarts)
- Consumer group support for reliable delivery
- Message acknowledgment
- Automatic retry for failed deliveries
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class HITLMessageType(str, Enum):
    """Type of HITL message."""

    RESPONSE = "response"  # User response to HITL request
    TIMEOUT = "timeout"  # Request timed out
    CANCEL = "cancel"  # Request cancelled
    HEARTBEAT = "heartbeat"  # Keep-alive signal


@dataclass
class HITLMessage:
    """
    A message in the HITL message bus.

    Attributes:
        message_id: Unique message ID (assigned by the bus)
        request_id: HITL request ID this message relates to
        message_type: Type of message (response, timeout, cancel)
        payload: Message payload data
        timestamp: When the message was created
        metadata: Additional metadata
    """

    message_id: str
    request_id: str
    message_type: HITLMessageType
    payload: dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "message_id": self.message_id,
            "request_id": self.request_id,
            "message_type": self.message_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp.isoformat(),
            "metadata": self.metadata or {},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HITLMessage":
        """Create from dictionary."""
        return cls(
            message_id=data.get("message_id", ""),
            request_id=data.get("request_id", ""),
            message_type=HITLMessageType(data.get("message_type", "response")),
            payload=data.get("payload", {}),
            timestamp=(
                datetime.fromisoformat(data["timestamp"])
                if isinstance(data.get("timestamp"), str)
                else data.get("timestamp", datetime.now(UTC))
            ),
            metadata=data.get("metadata"),
        )


class HITLMessageBusPort(ABC):
    """
    Abstract port for HITL cross-process messaging.

    This port provides reliable message delivery between:
    - API Process: Receives user responses via WebSocket/HTTP
    - Worker Process: Waits for responses while executing agent tools

    Implementation Requirements:
    - Messages must persist until acknowledged
    - Consumer groups should be used for at-least-once delivery
    - Implementations should handle reconnection gracefully
    - Messages should be automatically cleaned up after acknowledgment
    """

    @abstractmethod
    async def publish_response(
        self,
        request_id: str,
        response_key: str,
        response_value: Any,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """
        Publish a response to an HITL request.

        This is called by the API process when a user responds to an HITL request.
        The response is delivered to the Worker process waiting on this request.

        Args:
            request_id: HITL request ID
            response_key: Key for the response (e.g., "decision", "answer", "values")
            response_value: The response value
            metadata: Optional additional metadata

        Returns:
            Message ID assigned by the bus
        """
        pass

    @abstractmethod
    async def subscribe_for_response(
        self,
        request_id: str,
        consumer_group: str,
        consumer_name: str,
        timeout_ms: int | None = None,
    ) -> AsyncIterator[HITLMessage]:
        """
        Subscribe to receive responses for an HITL request.

        This is called by the Worker process to wait for user responses.
        Uses consumer groups for reliable delivery.

        Args:
            request_id: HITL request ID to wait for
            consumer_group: Consumer group name (e.g., "hitl-decision-workers")
            consumer_name: Consumer name within the group (e.g., "worker-1")
            timeout_ms: Block timeout in milliseconds (None = wait indefinitely)

        Yields:
            HITLMessage objects as they arrive
        """
        pass

    @abstractmethod
    async def acknowledge(
        self,
        request_id: str,
        consumer_group: str,
        message_ids: list[str],
    ) -> int:
        """
        Acknowledge receipt of messages.

        This removes the messages from the pending list for the consumer group.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            message_ids: List of message IDs to acknowledge

        Returns:
            Number of messages acknowledged
        """
        pass

    @abstractmethod
    async def create_consumer_group(
        self,
        request_id: str,
        consumer_group: str,
        start_from_latest: bool = True,
    ) -> bool:
        """
        Create a consumer group for an HITL request stream.

        This should be called before subscribing to ensure the group exists.
        Idempotent - safe to call multiple times.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            start_from_latest: If True, only read new messages; if False, read from beginning

        Returns:
            True if created successfully (or already exists)
        """
        pass

    @abstractmethod
    async def get_pending_messages(
        self,
        request_id: str,
        consumer_group: str,
        count: int = 10,
    ) -> list[HITLMessage]:
        """
        Get pending messages that haven't been acknowledged.

        This is useful for recovery after a consumer restart.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            count: Maximum number of pending messages to return

        Returns:
            List of pending messages
        """
        pass

    @abstractmethod
    async def claim_pending_messages(
        self,
        request_id: str,
        consumer_group: str,
        consumer_name: str,
        min_idle_ms: int,
        message_ids: list[str],
    ) -> list[HITLMessage]:
        """
        Claim pending messages from another consumer.

        This is used when a consumer dies and another consumer needs to
        take over its pending messages.

        Args:
            request_id: HITL request ID
            consumer_group: Consumer group name
            consumer_name: Consumer to claim messages for
            min_idle_ms: Minimum idle time for messages to be claimable
            message_ids: List of message IDs to claim

        Returns:
            List of claimed messages
        """
        pass

    @abstractmethod
    async def cleanup_stream(
        self,
        request_id: str,
        max_len: int | None = None,
    ) -> int:
        """
        Clean up a stream (trim old messages or delete entirely).

        Args:
            request_id: HITL request ID
            max_len: If provided, trim to this length; if None, delete the stream

        Returns:
            Number of messages removed (or 0 if deleted)
        """
        pass

    @abstractmethod
    async def stream_exists(self, request_id: str) -> bool:
        """
        Check if a stream exists for the given request.

        Args:
            request_id: HITL request ID

        Returns:
            True if stream exists
        """
        pass

    # =========================================================================
    # Convenience methods with default implementations
    # =========================================================================

    async def publish_decision_response(
        self,
        request_id: str,
        decision: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Convenience method for publishing decision responses."""
        return await self.publish_response(
            request_id=request_id,
            response_key="decision",
            response_value=decision,
            metadata=metadata,
        )

    async def publish_clarification_response(
        self,
        request_id: str,
        answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Convenience method for publishing clarification responses."""
        return await self.publish_response(
            request_id=request_id,
            response_key="answer",
            response_value=answer,
            metadata=metadata,
        )

    async def publish_env_var_response(
        self,
        request_id: str,
        values: dict[str, str],
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Convenience method for publishing environment variable responses."""
        return await self.publish_response(
            request_id=request_id,
            response_key="values",
            response_value=values,
            metadata=metadata,
        )

    async def publish_timeout(
        self,
        request_id: str,
        default_value: Any | None = None,
    ) -> str:
        """Publish a timeout notification."""
        return await self.publish_response(
            request_id=request_id,
            response_key="timeout",
            response_value=default_value,
            metadata={"message_type": HITLMessageType.TIMEOUT.value},
        )

    async def publish_cancel(
        self,
        request_id: str,
        reason: str | None = None,
    ) -> str:
        """Publish a cancellation notification."""
        return await self.publish_response(
            request_id=request_id,
            response_key="cancel",
            response_value=reason,
            metadata={"message_type": HITLMessageType.CANCEL.value},
        )
