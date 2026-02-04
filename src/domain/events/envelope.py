"""Event Envelope - Wrapper for all domain events.

The EventEnvelope provides a standardized wrapper for all domain events,
enabling:
- Schema versioning for backward/forward compatibility
- Event correlation and causation tracking
- Metadata for observability and debugging

Event Format (wire format):
{
    "schema_version": "1.0",
    "event_id": "evt_abc123",
    "event_type": "thought",
    "timestamp": "2024-01-01T00:00:00Z",
    "source": "memstack",
    "correlation_id": "corr_xyz",  // Optional: request/trace ID
    "causation_id": "evt_parent",   // Optional: parent event ID
    "payload": { ... },             // Event-specific data
    "metadata": { ... }             // Additional context
}
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional, TypeVar

from src.domain.events.types import AgentEventType


@dataclass(frozen=True)
class EventEnvelope:
    """Envelope wrapper for domain events.

    This provides a standardized structure for all events in the system,
    enabling schema versioning and event correlation.

    Attributes:
        schema_version: Version of the event schema (e.g., "1.0")
        event_id: Unique identifier for this event
        event_type: Type of the event (from AgentEventType)
        timestamp: When the event occurred (ISO 8601 format)
        source: System that generated the event
        correlation_id: Optional ID for correlating related events
        causation_id: Optional ID of the event that caused this event
        payload: Event-specific data
        metadata: Additional context (e.g., user_id, tenant_id)
    """

    event_type: str
    payload: Dict[str, Any]
    schema_version: str = "1.0"
    event_id: str = field(default_factory=lambda: f"evt_{uuid.uuid4().hex[:12]}")
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    source: str = "memstack"
    correlation_id: Optional[str] = None
    causation_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization.

        Returns:
            Dictionary representation of the envelope
        """
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "event_type": self.event_type,
            "timestamp": self.timestamp,
            "source": self.source,
            "correlation_id": self.correlation_id,
            "causation_id": self.causation_id,
            "payload": self.payload,
            "metadata": self.metadata,
        }

    def to_json(self) -> str:
        """Convert to JSON string.

        Returns:
            JSON string representation
        """
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EventEnvelope":
        """Create envelope from dictionary.

        Args:
            data: Dictionary containing envelope fields

        Returns:
            EventEnvelope instance
        """
        return cls(
            schema_version=data.get("schema_version", "1.0"),
            event_id=data.get("event_id", f"evt_{uuid.uuid4().hex[:12]}"),
            event_type=data.get("event_type", ""),
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            source=data.get("source", "memstack"),
            correlation_id=data.get("correlation_id"),
            causation_id=data.get("causation_id"),
            payload=data.get("payload", {}),
            metadata=data.get("metadata", {}),
        )

    @classmethod
    def from_json(cls, json_str: str) -> "EventEnvelope":
        """Create envelope from JSON string.

        Args:
            json_str: JSON string

        Returns:
            EventEnvelope instance
        """
        return cls.from_dict(json.loads(json_str))

    @classmethod
    def wrap(
        cls,
        event_type: AgentEventType,
        payload: Dict[str, Any],
        correlation_id: Optional[str] = None,
        causation_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        schema_version: str = "1.0",
    ) -> "EventEnvelope":
        """Create an envelope for a domain event.

        This is the primary factory method for creating envelopes.

        Args:
            event_type: The type of event
            payload: Event-specific data
            correlation_id: Optional correlation ID
            causation_id: Optional causation ID
            metadata: Optional metadata
            schema_version: Schema version (default "1.0")

        Returns:
            EventEnvelope wrapping the event
        """
        return cls(
            schema_version=schema_version,
            event_type=event_type.value,
            payload=payload,
            correlation_id=correlation_id,
            causation_id=causation_id,
            metadata=metadata or {},
        )

    def with_metadata(self, **kwargs: Any) -> "EventEnvelope":
        """Create a new envelope with additional metadata.

        Args:
            **kwargs: Key-value pairs to add to metadata

        Returns:
            New EventEnvelope with updated metadata
        """
        new_metadata = {**self.metadata, **kwargs}
        return EventEnvelope(
            schema_version=self.schema_version,
            event_id=self.event_id,
            event_type=self.event_type,
            timestamp=self.timestamp,
            source=self.source,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            payload=self.payload,
            metadata=new_metadata,
        )

    def with_correlation(
        self,
        correlation_id: str,
        causation_id: Optional[str] = None,
    ) -> "EventEnvelope":
        """Create a new envelope with correlation information.

        Args:
            correlation_id: Correlation ID for the event
            causation_id: Optional causation ID

        Returns:
            New EventEnvelope with correlation info
        """
        return EventEnvelope(
            schema_version=self.schema_version,
            event_id=self.event_id,
            event_type=self.event_type,
            timestamp=self.timestamp,
            source=self.source,
            correlation_id=correlation_id,
            causation_id=causation_id or self.causation_id,
            payload=self.payload,
            metadata=self.metadata,
        )


# Type variable for generic envelope handling
E = TypeVar("E", bound=EventEnvelope)


def create_child_envelope(
    parent: EventEnvelope,
    event_type: AgentEventType,
    payload: Dict[str, Any],
    **extra_metadata: Any,
) -> EventEnvelope:
    """Create a child envelope from a parent envelope.

    The child inherits the correlation_id and uses the parent's
    event_id as its causation_id.

    Args:
        parent: Parent envelope
        event_type: Type of the child event
        payload: Child event payload
        **extra_metadata: Additional metadata for the child

    Returns:
        New EventEnvelope as a child of the parent
    """
    return EventEnvelope.wrap(
        event_type=event_type,
        payload=payload,
        correlation_id=parent.correlation_id,
        causation_id=parent.event_id,
        metadata={**parent.metadata, **extra_metadata},
    )
