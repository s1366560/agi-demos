"""Domain Events Package.

This package contains domain events and the unified event type definitions.

The Single Source of Truth for event types is in types.py.

Schema versioning is handled by:
- envelope.py: Event envelope structure
- registry.py: Schema registration and migration
- serialization.py: Version-aware serialization
"""

from src.domain.events.agent_events import (
    AgentDomainEvent,
    get_event_type_docstring,
)
from src.domain.events.envelope import (
    EventEnvelope,
    create_child_envelope,
)
from src.domain.events.registry import (
    EventSchemaRegistry,
    MigrationInfo,
    SchemaInfo,
    get_schema,
    migrate_event,
)
from src.domain.events.serialization import (
    DeserializationError,
    DeserializationResult,
    EventSerializer,
    SerializationError,
    VersionMismatchError,
    create_serializer,
    deserialize_event,
    serialize_event,
)
from src.domain.events.types import (
    DELTA_EVENT_TYPES,
    HITL_EVENT_TYPES,
    INTERNAL_EVENT_TYPES,
    TERMINAL_EVENT_TYPES,
    AgentEventType,
    EventCategory,
    get_event_category,
    get_frontend_event_types,
    is_delta_event,
    is_hitl_event,
    is_terminal_event,
)

__all__ = [
    # Types
    "AgentEventType",
    "EventCategory",
    # Type sets
    "DELTA_EVENT_TYPES",
    "HITL_EVENT_TYPES",
    "INTERNAL_EVENT_TYPES",
    "TERMINAL_EVENT_TYPES",
    # Utility functions
    "get_event_category",
    "get_frontend_event_types",
    "is_delta_event",
    "is_hitl_event",
    "is_terminal_event",
    # Domain events
    "AgentDomainEvent",
    "get_event_type_docstring",
    # Envelope
    "EventEnvelope",
    "create_child_envelope",
    # Schema Registry
    "EventSchemaRegistry",
    "SchemaInfo",
    "MigrationInfo",
    "get_schema",
    "migrate_event",
    # Serialization
    "EventSerializer",
    "DeserializationResult",
    "SerializationError",
    "DeserializationError",
    "VersionMismatchError",
    "serialize_event",
    "deserialize_event",
    "create_serializer",
]
