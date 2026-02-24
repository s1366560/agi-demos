"""Event Serialization - Version-aware serialization and deserialization.

This module provides serialization utilities that handle schema versioning
automatically, ensuring backward and forward compatibility.

Usage:
    serializer = EventSerializer()

    # Serialize an event
    json_str = serializer.serialize(event)

    # Deserialize with automatic version migration
    event = serializer.deserialize(json_str)
"""

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from src.domain.events.envelope import EventEnvelope
from src.domain.events.registry import EventSchemaRegistry
from src.domain.events.types import AgentEventType

logger = logging.getLogger(__name__)


class SerializationError(Exception):
    """Error during event serialization."""

    pass


class DeserializationError(Exception):
    """Error during event deserialization."""

    pass


class VersionMismatchError(Exception):
    """Schema version mismatch error."""

    pass


@dataclass
class DeserializationResult:
    """Result of deserializing an event.

    Attributes:
        envelope: The deserialized event envelope
        migrated: Whether the event was migrated from an older version
        original_version: Original schema version (if migrated)
        target_version: Target schema version (if migrated)
    """

    envelope: EventEnvelope
    migrated: bool = False
    original_version: str | None = None
    target_version: str | None = None


class EventSerializer:
    """Version-aware event serializer.

    Handles serialization and deserialization of events with automatic
    schema version migration.
    """

    def __init__(
        self,
        *,
        auto_migrate: bool = True,
        target_version: str = "latest",
        strict_mode: bool = False,
    ) -> None:
        """Initialize the serializer.

        Args:
            auto_migrate: Whether to automatically migrate old versions
            target_version: Target version for migrations ("latest" or specific)
            strict_mode: If True, raise errors on unknown event types
        """
        self.auto_migrate = auto_migrate
        self.target_version = target_version
        self.strict_mode = strict_mode

    def serialize(
        self,
        envelope: EventEnvelope,
        *,
        pretty: bool = False,
    ) -> str:
        """Serialize an event envelope to JSON.

        Args:
            envelope: Event envelope to serialize
            pretty: Whether to format output with indentation

        Returns:
            JSON string
        """
        try:
            data = envelope.to_dict()
            if pretty:
                return json.dumps(data, default=self._json_serializer, indent=2)
            return json.dumps(data, default=self._json_serializer)
        except Exception as e:
            raise SerializationError(f"Failed to serialize event: {e}") from e

    def deserialize(
        self,
        json_str: str,
        *,
        expected_type: str | None = None,
    ) -> DeserializationResult:
        """Deserialize JSON to an event envelope.

        Args:
            json_str: JSON string to deserialize
            expected_type: Optional expected event type for validation

        Returns:
            DeserializationResult containing the envelope and migration info
        """
        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            raise DeserializationError(f"Invalid JSON: {e}") from e

        return self.deserialize_dict(data, expected_type=expected_type)

    def deserialize_dict(
        self,
        data: dict[str, Any],
        *,
        expected_type: str | None = None,
    ) -> DeserializationResult:
        """Deserialize a dictionary to an event envelope.

        Args:
            data: Dictionary to deserialize
            expected_type: Optional expected event type for validation

        Returns:
            DeserializationResult containing the envelope and migration info
        """
        # Validate expected type
        event_type = data.get("event_type")
        if expected_type and event_type != expected_type:
            raise DeserializationError(f"Expected event type '{expected_type}', got '{event_type}'")

        # Get schema version
        original_version = data.get("schema_version", "1.0")

        # Determine target version
        if self.target_version == "latest":
            target_version = EventSchemaRegistry.get_latest_version(event_type)
            if not target_version:
                target_version = original_version
        else:
            target_version = self.target_version

        # Migrate if needed
        migrated = False
        if self.auto_migrate and original_version != target_version:
            try:
                payload = data.get("payload", {})
                migrated_payload = EventSchemaRegistry.migrate(
                    payload,
                    event_type,
                    original_version,
                    target_version,
                )
                data["payload"] = migrated_payload
                data["schema_version"] = target_version
                migrated = True
                logger.debug(f"Migrated {event_type} from v{original_version} to v{target_version}")
            except ValueError:
                # No migration path, keep original version
                if self.strict_mode:
                    raise
                logger.debug(
                    f"No migration path for {event_type} "
                    f"from v{original_version} to v{target_version}"
                )

        # Create envelope
        envelope = EventEnvelope.from_dict(data)

        return DeserializationResult(
            envelope=envelope,
            migrated=migrated,
            original_version=original_version if migrated else None,
            target_version=target_version if migrated else None,
        )

    def serialize_batch(
        self,
        envelopes: list[EventEnvelope],
        *,
        format: str = "jsonl",
    ) -> str:
        """Serialize multiple events.

        Args:
            envelopes: List of event envelopes
            format: Output format ("jsonl" or "json_array")

        Returns:
            Serialized string
        """
        if format == "jsonl":
            lines = [self.serialize(e) for e in envelopes]
            return "\n".join(lines)
        elif format == "json_array":
            data = [e.to_dict() for e in envelopes]
            return json.dumps(data, default=self._json_serializer)
        else:
            raise ValueError(f"Unknown format: {format}")

    def deserialize_batch(
        self,
        data: str,
        *,
        format: str = "jsonl",
    ) -> list[DeserializationResult]:
        """Deserialize multiple events.

        Args:
            data: Serialized data
            format: Input format ("jsonl" or "json_array")

        Returns:
            List of DeserializationResult
        """
        if format == "jsonl":
            lines = [line.strip() for line in data.split("\n") if line.strip()]
            return [self.deserialize(line) for line in lines]
        elif format == "json_array":
            items = json.loads(data)
            return [self.deserialize_dict(item) for item in items]
        else:
            raise ValueError(f"Unknown format: {format}")

    @staticmethod
    def _json_serializer(obj: Any) -> Any:
        """Custom JSON serializer for special types."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, AgentEventType):
            return obj.value
        if hasattr(obj, "to_dict"):
            return obj.to_dict()
        if hasattr(obj, "__dict__"):
            return obj.__dict__
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# Default serializer instance
_default_serializer = EventSerializer()


def serialize_event(envelope: EventEnvelope, **kwargs: Any) -> str:
    """Serialize an event envelope to JSON using the default serializer."""
    return _default_serializer.serialize(envelope, **kwargs)


def deserialize_event(
    json_str: str,
    **kwargs: Any,
) -> DeserializationResult:
    """Deserialize JSON to an event envelope using the default serializer."""
    return _default_serializer.deserialize(json_str, **kwargs)


def create_serializer(**kwargs: Any) -> EventSerializer:
    """Create a custom event serializer.

    Args:
        **kwargs: Arguments to pass to EventSerializer

    Returns:
        Configured EventSerializer instance
    """
    return EventSerializer(**kwargs)
