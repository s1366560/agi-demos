"""Tests for Event Schema Versioning System.

Tests the envelope, registry, and serialization modules.
"""

import json
from typing import Any, Dict

import pytest

from src.domain.events.envelope import EventEnvelope, create_child_envelope
from src.domain.events.registry import EventSchemaRegistry
from src.domain.events.serialization import (
    DeserializationError,
    EventSerializer,
)
from src.domain.events.types import AgentEventType


class TestEventEnvelope:
    """Tests for EventEnvelope."""

    def test_create_envelope(self):
        """Test basic envelope creation."""
        envelope = EventEnvelope(
            event_type="thought",
            payload={"content": "test"},
        )

        assert envelope.event_type == "thought"
        assert envelope.schema_version == "1.0"
        assert envelope.source == "memstack"
        assert envelope.payload == {"content": "test"}
        assert envelope.event_id.startswith("evt_")

    def test_wrap_event(self):
        """Test creating envelope via wrap factory method."""
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test thought", "thought_level": "task"},
            correlation_id="corr_123",
        )

        assert envelope.event_type == "thought"
        assert envelope.correlation_id == "corr_123"
        assert envelope.payload["content"] == "test thought"

    def test_to_dict_and_back(self):
        """Test serialization round-trip."""
        original = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test"},
            metadata={"user_id": "user_123"},
        )

        data = original.to_dict()
        restored = EventEnvelope.from_dict(data)

        assert restored.event_type == original.event_type
        assert restored.event_id == original.event_id
        assert restored.payload == original.payload
        assert restored.metadata == original.metadata

    def test_to_json_and_back(self):
        """Test JSON serialization round-trip."""
        original = EventEnvelope.wrap(
            event_type=AgentEventType.ACT,
            payload={"tool_name": "bash", "parameters": {"command": "ls"}},
        )

        json_str = original.to_json()
        restored = EventEnvelope.from_json(json_str)

        assert restored.event_type == original.event_type
        assert restored.payload == original.payload

    def test_with_metadata(self):
        """Test adding metadata creates new envelope."""
        original = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test"},
        )

        updated = original.with_metadata(user_id="user_123", tenant_id="tenant_456")

        assert original.metadata == {}  # Original unchanged
        assert updated.metadata == {"user_id": "user_123", "tenant_id": "tenant_456"}
        assert updated.event_id == original.event_id  # Same event

    def test_with_correlation(self):
        """Test adding correlation info."""
        original = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test"},
        )

        updated = original.with_correlation(
            correlation_id="trace_abc",
            causation_id="evt_parent",
        )

        assert updated.correlation_id == "trace_abc"
        assert updated.causation_id == "evt_parent"
        assert original.correlation_id is None  # Original unchanged


class TestCreateChildEnvelope:
    """Tests for create_child_envelope function."""

    def test_child_inherits_correlation(self):
        """Test child envelope inherits correlation_id."""
        parent = EventEnvelope.wrap(
            event_type=AgentEventType.START,
            payload={},
            correlation_id="trace_123",
        )

        child = create_child_envelope(
            parent=parent,
            event_type=AgentEventType.THOUGHT,
            payload={"content": "thinking..."},
        )

        assert child.correlation_id == parent.correlation_id
        assert child.causation_id == parent.event_id

    def test_child_inherits_metadata(self):
        """Test child envelope inherits parent metadata."""
        parent = EventEnvelope.wrap(
            event_type=AgentEventType.START,
            payload={},
            metadata={"user_id": "user_123"},
        )

        child = create_child_envelope(
            parent=parent,
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test"},
            extra_key="extra_value",
        )

        assert child.metadata["user_id"] == "user_123"
        assert child.metadata["extra_key"] == "extra_value"


class TestEventSchemaRegistry:
    """Tests for EventSchemaRegistry."""

    def setup_method(self):
        """Clear registry before each test."""
        EventSchemaRegistry.clear()

    def test_register_schema(self):
        """Test registering a schema."""

        @EventSchemaRegistry.register("test_event", "1.0")
        class TestEventV1:
            pass

        assert EventSchemaRegistry.is_registered("test_event", "1.0")
        assert EventSchemaRegistry.get_schema("test_event", "1.0") is TestEventV1

    def test_get_latest_version(self):
        """Test getting latest schema version."""

        @EventSchemaRegistry.register("test_event", "1.0")
        class TestEventV1:
            pass

        @EventSchemaRegistry.register("test_event", "2.0")
        class TestEventV2:
            pass

        @EventSchemaRegistry.register("test_event", "1.5")
        class TestEventV15:
            pass

        assert EventSchemaRegistry.get_latest_version("test_event") == "2.0"
        assert EventSchemaRegistry.get_schema("test_event", "latest") is TestEventV2

    def test_register_migration(self):
        """Test registering a migration."""

        @EventSchemaRegistry.register("test_event", "1.0")
        class TestEventV1:
            pass

        @EventSchemaRegistry.register("test_event", "2.0")
        class TestEventV2:
            pass

        @EventSchemaRegistry.register_migration("test_event", "1.0", "2.0")
        def migrate_v1_to_v2(data: Dict[str, Any]) -> Dict[str, Any]:
            return {**data, "new_field": "default_value"}

        # Test migration
        original = {"content": "test"}
        migrated = EventSchemaRegistry.migrate(
            original, "test_event", "1.0", "2.0"
        )

        assert migrated["content"] == "test"
        assert migrated["new_field"] == "default_value"

    def test_migration_path_finding(self):
        """Test finding multi-step migration path."""

        @EventSchemaRegistry.register("test_event", "1.0")
        class V1:
            pass

        @EventSchemaRegistry.register("test_event", "2.0")
        class V2:
            pass

        @EventSchemaRegistry.register("test_event", "3.0")
        class V3:
            pass

        @EventSchemaRegistry.register_migration("test_event", "1.0", "2.0")
        def migrate_1_to_2(data):
            return {**data, "v2_field": True}

        @EventSchemaRegistry.register_migration("test_event", "2.0", "3.0")
        def migrate_2_to_3(data):
            return {**data, "v3_field": True}

        # Migrate from 1.0 to 3.0 (should find path through 2.0)
        original = {"content": "test"}
        migrated = EventSchemaRegistry.migrate(
            original, "test_event", "1.0", "3.0"
        )

        assert migrated["v2_field"] is True
        assert migrated["v3_field"] is True

    def test_deprecated_schema_warning(self, caplog):
        """Test deprecation warning for deprecated schemas."""

        @EventSchemaRegistry.register(
            "old_event",
            "1.0",
            deprecated=True,
            deprecation_message="Use v2.0 instead",
        )
        class OldEvent:
            pass

        import logging
        caplog.set_level(logging.WARNING)

        schema = EventSchemaRegistry.get_schema("old_event", "1.0")
        assert schema is OldEvent
        assert "deprecated" in caplog.text.lower()

    def test_list_schemas(self):
        """Test listing all registered schemas."""

        @EventSchemaRegistry.register("event_a", "1.0")
        class EventA1:
            pass

        @EventSchemaRegistry.register("event_a", "2.0")
        class EventA2:
            pass

        @EventSchemaRegistry.register("event_b", "1.0")
        class EventB1:
            pass

        all_schemas = EventSchemaRegistry.list_schemas()
        assert len(all_schemas) == 3

        a_schemas = EventSchemaRegistry.list_schemas("event_a")
        assert len(a_schemas) == 2


class TestEventSerializer:
    """Tests for EventSerializer."""

    def setup_method(self):
        """Clear registry before each test."""
        EventSchemaRegistry.clear()

    def test_serialize_envelope(self):
        """Test serializing an envelope to JSON."""
        serializer = EventSerializer()
        envelope = EventEnvelope.wrap(
            event_type=AgentEventType.THOUGHT,
            payload={"content": "test thought"},
        )

        json_str = serializer.serialize(envelope)
        data = json.loads(json_str)

        assert data["event_type"] == "thought"
        assert data["payload"]["content"] == "test thought"
        assert data["schema_version"] == "1.0"

    def test_deserialize_envelope(self):
        """Test deserializing JSON to envelope."""
        serializer = EventSerializer(auto_migrate=False)
        json_str = json.dumps({
            "schema_version": "1.0",
            "event_id": "evt_test123",
            "event_type": "thought",
            "timestamp": "2024-01-01T00:00:00Z",
            "source": "memstack",
            "payload": {"content": "test"},
            "metadata": {},
        })

        result = serializer.deserialize(json_str)

        assert result.envelope.event_type == "thought"
        assert result.envelope.event_id == "evt_test123"
        assert result.migrated is False

    def test_auto_migrate_on_deserialize(self):
        """Test automatic migration during deserialization."""
        # Register schemas and migration
        @EventSchemaRegistry.register("custom_event", "1.0")
        class V1:
            pass

        @EventSchemaRegistry.register("custom_event", "2.0")
        class V2:
            pass

        @EventSchemaRegistry.register_migration("custom_event", "1.0", "2.0")
        def migrate(data):
            return {**data, "new_field": "migrated"}

        serializer = EventSerializer(auto_migrate=True)
        json_str = json.dumps({
            "schema_version": "1.0",
            "event_type": "custom_event",
            "payload": {"old_field": "value"},
            "metadata": {},
        })

        result = serializer.deserialize(json_str)

        assert result.migrated is True
        assert result.original_version == "1.0"
        assert result.target_version == "2.0"
        assert result.envelope.payload.get("new_field") == "migrated"

    def test_serialize_batch_jsonl(self):
        """Test batch serialization to JSONL."""
        serializer = EventSerializer()
        envelopes = [
            EventEnvelope.wrap(AgentEventType.START, {"session": "s1"}),
            EventEnvelope.wrap(AgentEventType.THOUGHT, {"content": "thinking"}),
            EventEnvelope.wrap(AgentEventType.COMPLETE, {"summary": "done"}),
        ]

        result = serializer.serialize_batch(envelopes, format="jsonl")
        lines = result.strip().split("\n")

        assert len(lines) == 3
        # Each line should be valid JSON
        for line in lines:
            data = json.loads(line)
            assert "event_type" in data

    def test_deserialize_batch_jsonl(self):
        """Test batch deserialization from JSONL."""
        serializer = EventSerializer(auto_migrate=False)
        jsonl = "\n".join([
            '{"schema_version": "1.0", "event_type": "start", "payload": {}, "metadata": {}}',
            '{"schema_version": "1.0", "event_type": "thought", "payload": {"content": "test"}, "metadata": {}}',
        ])

        results = serializer.deserialize_batch(jsonl, format="jsonl")

        assert len(results) == 2
        assert results[0].envelope.event_type == "start"
        assert results[1].envelope.event_type == "thought"

    def test_invalid_json_raises_error(self):
        """Test that invalid JSON raises DeserializationError."""
        serializer = EventSerializer()

        with pytest.raises(DeserializationError):
            serializer.deserialize("not valid json")


class TestSchemaVersionCompatibility:
    """Integration tests for schema version compatibility."""

    def setup_method(self):
        """Clear registry before each test."""
        EventSchemaRegistry.clear()

    def test_backward_compatibility_new_optional_field(self):
        """Test backward compatibility: new optional field."""
        # v1.0 has only content
        @EventSchemaRegistry.register("thought", "1.0")
        class ThoughtV1:
            content: str

        # v2.0 adds optional thinking_time
        @EventSchemaRegistry.register("thought", "2.0")
        class ThoughtV2:
            content: str
            thinking_time_ms: int = None

        @EventSchemaRegistry.register_migration("thought", "1.0", "2.0")
        def migrate(data):
            return {**data, "thinking_time_ms": None}

        # Old event (v1.0) should be deserializable by new code
        serializer = EventSerializer(auto_migrate=True)
        old_event = json.dumps({
            "schema_version": "1.0",
            "event_type": "thought",
            "payload": {"content": "old thought"},
            "metadata": {},
        })

        result = serializer.deserialize(old_event)

        assert result.envelope.payload["content"] == "old thought"
        assert result.envelope.payload.get("thinking_time_ms") is None
        assert result.migrated is True

    def test_forward_compatibility_ignore_unknown_fields(self):
        """Test forward compatibility: ignore unknown fields."""
        # Register only v1.0
        @EventSchemaRegistry.register("thought", "1.0")
        class ThoughtV1:
            content: str

        # Receive an event with v2.0 schema (has extra fields)
        serializer = EventSerializer(auto_migrate=False)  # Don't try to migrate
        new_event = json.dumps({
            "schema_version": "2.0",
            "event_type": "thought",
            "payload": {
                "content": "new thought",
                "thinking_time_ms": 500,  # Unknown field
                "reasoning_steps": ["a", "b"],  # Unknown field
            },
            "metadata": {},
        })

        result = serializer.deserialize(new_event)

        # Should deserialize successfully, keeping all fields
        assert result.envelope.payload["content"] == "new thought"
        assert result.envelope.payload["thinking_time_ms"] == 500
