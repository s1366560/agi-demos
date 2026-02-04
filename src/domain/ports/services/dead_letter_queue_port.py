"""Dead Letter Queue Port - Interface for handling failed events.

The DLQ provides reliability for the event system by:
1. Capturing failed events that couldn't be processed
2. Storing error context for debugging
3. Supporting manual and automatic retry
4. Providing visibility through metrics and API

Usage:
    class RedisDLQAdapter(DeadLetterQueuePort):
        async def send_to_dlq(self, event, error, ...):
            # Store failed event in Redis
            pass

        async def retry_message(self, message_id):
            # Republish to original queue
            pass
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class DLQMessageStatus(str, Enum):
    """Status of a DLQ message."""

    PENDING = "pending"  # Awaiting retry or manual action
    RETRYING = "retrying"  # Currently being retried
    DISCARDED = "discarded"  # Manually discarded
    EXPIRED = "expired"  # Auto-expired after TTL
    RESOLVED = "resolved"  # Successfully retried


@dataclass
class DeadLetterMessage:
    """A message in the dead letter queue.

    Attributes:
        id: Unique identifier for this DLQ entry
        event_id: Original event ID
        event_type: Type of the original event
        event_data: Serialized event data
        routing_key: Original routing key
        error: Error message that caused the failure
        error_type: Type/class of the error
        error_traceback: Optional stack trace
        retry_count: Number of retry attempts
        max_retries: Maximum retry attempts allowed
        first_failed_at: When the event first failed
        last_failed_at: When the most recent failure occurred
        next_retry_at: When the next retry should occur
        status: Current status of the DLQ message
        metadata: Additional context (consumer, version, etc.)
    """

    id: str = field(default_factory=lambda: f"dlq_{uuid.uuid4().hex[:12]}")
    event_id: str = ""
    event_type: str = ""
    event_data: str = ""
    routing_key: str = ""
    error: str = ""
    error_type: str = ""
    error_traceback: Optional[str] = None
    retry_count: int = 0
    max_retries: int = 3
    first_failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_failed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    next_retry_at: Optional[datetime] = None
    status: DLQMessageStatus = DLQMessageStatus.PENDING
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def can_retry(self) -> bool:
        """Check if this message can be retried."""
        return (
            self.status == DLQMessageStatus.PENDING
            and self.retry_count < self.max_retries
        )

    @property
    def age_seconds(self) -> float:
        """Get the age of this DLQ message in seconds."""
        return (datetime.now(timezone.utc) - self.first_failed_at).total_seconds()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "event_data": self.event_data,
            "routing_key": self.routing_key,
            "error": self.error,
            "error_type": self.error_type,
            "error_traceback": self.error_traceback,
            "retry_count": self.retry_count,
            "max_retries": self.max_retries,
            "first_failed_at": self.first_failed_at.isoformat(),
            "last_failed_at": self.last_failed_at.isoformat(),
            "next_retry_at": self.next_retry_at.isoformat() if self.next_retry_at else None,
            "status": self.status.value,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeadLetterMessage":
        """Create from dictionary."""
        return cls(
            id=data.get("id", f"dlq_{uuid.uuid4().hex[:12]}"),
            event_id=data.get("event_id", ""),
            event_type=data.get("event_type", ""),
            event_data=data.get("event_data", ""),
            routing_key=data.get("routing_key", ""),
            error=data.get("error", ""),
            error_type=data.get("error_type", ""),
            error_traceback=data.get("error_traceback"),
            retry_count=data.get("retry_count", 0),
            max_retries=data.get("max_retries", 3),
            first_failed_at=datetime.fromisoformat(data["first_failed_at"])
            if data.get("first_failed_at")
            else datetime.now(timezone.utc),
            last_failed_at=datetime.fromisoformat(data["last_failed_at"])
            if data.get("last_failed_at")
            else datetime.now(timezone.utc),
            next_retry_at=datetime.fromisoformat(data["next_retry_at"])
            if data.get("next_retry_at")
            else None,
            status=DLQMessageStatus(data.get("status", "pending")),
            metadata=data.get("metadata", {}),
        )


@dataclass
class DLQStats:
    """Statistics about the dead letter queue.

    Attributes:
        total_messages: Total messages in DLQ
        pending_count: Messages awaiting action
        retrying_count: Messages currently being retried
        discarded_count: Manually discarded messages
        expired_count: Auto-expired messages
        resolved_count: Successfully retried messages
        oldest_message_age: Age of oldest pending message (seconds)
        error_type_counts: Count by error type
        event_type_counts: Count by event type
    """

    total_messages: int = 0
    pending_count: int = 0
    retrying_count: int = 0
    discarded_count: int = 0
    expired_count: int = 0
    resolved_count: int = 0
    oldest_message_age: float = 0.0
    error_type_counts: Dict[str, int] = field(default_factory=dict)
    event_type_counts: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "total_messages": self.total_messages,
            "pending_count": self.pending_count,
            "retrying_count": self.retrying_count,
            "discarded_count": self.discarded_count,
            "expired_count": self.expired_count,
            "resolved_count": self.resolved_count,
            "oldest_message_age_seconds": self.oldest_message_age,
            "error_type_counts": self.error_type_counts,
            "event_type_counts": self.event_type_counts,
        }


class DeadLetterQueuePort(ABC):
    """Port for dead letter queue operations.

    The DLQ captures events that fail processing and provides
    retry and visibility mechanisms.
    """

    @abstractmethod
    async def send_to_dlq(
        self,
        event_id: str,
        event_type: str,
        event_data: str,
        routing_key: str,
        error: str,
        error_type: str,
        *,
        error_traceback: Optional[str] = None,
        retry_count: int = 0,
        max_retries: int = 3,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Send a failed event to the dead letter queue.

        Args:
            event_id: Original event ID
            event_type: Type of the event
            event_data: Serialized event data
            routing_key: Original routing key
            error: Error message
            error_type: Type of the error
            error_traceback: Optional stack trace
            retry_count: Current retry count
            max_retries: Maximum retries allowed
            metadata: Additional context

        Returns:
            DLQ message ID
        """
        pass

    @abstractmethod
    async def get_message(self, message_id: str) -> Optional[DeadLetterMessage]:
        """Get a specific DLQ message.

        Args:
            message_id: DLQ message ID

        Returns:
            DeadLetterMessage or None if not found
        """
        pass

    @abstractmethod
    async def get_messages(
        self,
        *,
        status: Optional[DLQMessageStatus] = None,
        event_type: Optional[str] = None,
        error_type: Optional[str] = None,
        routing_key_pattern: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[DeadLetterMessage]:
        """Get DLQ messages with filtering.

        Args:
            status: Filter by status
            event_type: Filter by event type
            error_type: Filter by error type
            routing_key_pattern: Filter by routing key pattern
            limit: Maximum messages to return
            offset: Offset for pagination

        Returns:
            List of DeadLetterMessage
        """
        pass

    @abstractmethod
    async def retry_message(self, message_id: str) -> bool:
        """Retry a DLQ message.

        This should:
        1. Update status to RETRYING
        2. Increment retry_count
        3. Republish to original routing key
        4. On success, update status to RESOLVED
        5. On failure, update status back to PENDING

        Args:
            message_id: DLQ message ID

        Returns:
            True if retry was initiated
        """
        pass

    @abstractmethod
    async def retry_batch(
        self,
        message_ids: List[str],
    ) -> Dict[str, bool]:
        """Retry multiple DLQ messages.

        Args:
            message_ids: List of DLQ message IDs

        Returns:
            Dict mapping message_id to retry success
        """
        pass

    @abstractmethod
    async def discard_message(
        self,
        message_id: str,
        reason: str,
    ) -> bool:
        """Discard a DLQ message.

        Args:
            message_id: DLQ message ID
            reason: Reason for discarding

        Returns:
            True if message was discarded
        """
        pass

    @abstractmethod
    async def discard_batch(
        self,
        message_ids: List[str],
        reason: str,
    ) -> Dict[str, bool]:
        """Discard multiple DLQ messages.

        Args:
            message_ids: List of DLQ message IDs
            reason: Reason for discarding

        Returns:
            Dict mapping message_id to discard success
        """
        pass

    @abstractmethod
    async def get_stats(self) -> DLQStats:
        """Get DLQ statistics.

        Returns:
            DLQStats with queue statistics
        """
        pass

    @abstractmethod
    async def cleanup_expired(
        self,
        older_than_hours: int = 168,  # 1 week
    ) -> int:
        """Clean up expired DLQ messages.

        Args:
            older_than_hours: Remove messages older than this

        Returns:
            Number of messages cleaned up
        """
        pass

    @abstractmethod
    async def cleanup_resolved(
        self,
        older_than_hours: int = 24,
    ) -> int:
        """Clean up resolved DLQ messages.

        Args:
            older_than_hours: Remove resolved messages older than this

        Returns:
            Number of messages cleaned up
        """
        pass


class DLQError(Exception):
    """Base exception for DLQ operations."""

    pass


class DLQMessageNotFoundError(DLQError):
    """DLQ message not found."""

    def __init__(self, message_id: str):
        super().__init__(f"DLQ message not found: {message_id}")
        self.message_id = message_id


class DLQRetryError(DLQError):
    """Error during DLQ retry."""

    def __init__(self, message_id: str, reason: str):
        super().__init__(f"Failed to retry {message_id}: {reason}")
        self.message_id = message_id
        self.reason = reason
