"""Event Store port interface for event sourcing patterns.

Provides a standard interface for storing and replaying domain events,
enabling event-driven architectures and temporal queries.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional


class EventStorePort(ABC):
    """Port interface for event storage and replay.

    Supports append-only event storage with sequence ordering,
    stream-based retrieval, and temporal queries.
    """

    @abstractmethod
    async def append(
        self,
        stream_id: str,
        event_type: str,
        event_data: dict[str, Any],
        *,
        metadata: Optional[dict[str, Any]] = None,
    ) -> int:
        """Append an event to a stream.

        Args:
            stream_id: Identifier for the event stream (e.g., conversation_id)
            event_type: Type of the event (e.g., "user_message", "tool_executed")
            event_data: Event payload
            metadata: Optional metadata (user_id, tenant_id, etc.)

        Returns:
            Sequence number of the appended event
        """
        ...

    @abstractmethod
    async def get_events(
        self,
        stream_id: str,
        *,
        from_sequence: int = 0,
        to_sequence: Optional[int] = None,
        event_types: Optional[list[str]] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Retrieve events from a stream.

        Args:
            stream_id: Identifier for the event stream
            from_sequence: Start sequence (inclusive)
            to_sequence: End sequence (inclusive), None for latest
            event_types: Filter by event types
            limit: Maximum events to return

        Returns:
            List of event dictionaries with sequence_number, event_type,
            event_data, metadata, and created_at
        """
        ...

    @abstractmethod
    async def get_events_by_time_range(
        self,
        stream_id: str,
        *,
        start_time: datetime,
        end_time: Optional[datetime] = None,
        event_types: Optional[list[str]] = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Retrieve events within a time range.

        Args:
            stream_id: Identifier for the event stream
            start_time: Start of time range (inclusive)
            end_time: End of time range (inclusive), None for now
            event_types: Filter by event types
            limit: Maximum events to return

        Returns:
            List of event dictionaries ordered by timestamp
        """
        ...

    @abstractmethod
    async def get_latest_sequence(self, stream_id: str) -> int:
        """Get the latest sequence number for a stream.

        Args:
            stream_id: Identifier for the event stream

        Returns:
            Latest sequence number, or 0 if stream is empty
        """
        ...

    @abstractmethod
    async def get_stream_ids(
        self,
        *,
        prefix: Optional[str] = None,
        limit: int = 100,
    ) -> list[str]:
        """List available event stream IDs.

        Args:
            prefix: Optional prefix filter for stream IDs
            limit: Maximum stream IDs to return

        Returns:
            List of stream ID strings
        """
        ...
