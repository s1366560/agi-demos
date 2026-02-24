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
    # Type sets
    "DELTA_EVENT_TYPES",
    "HITL_EVENT_TYPES",
    "INTERNAL_EVENT_TYPES",
    "TERMINAL_EVENT_TYPES",
    # Domain events
    "AgentDomainEvent",
    # Types
    "AgentEventType",
    "DeserializationError",
    "DeserializationResult",
    "EventCategory",
    # Envelope
    "EventEnvelope",
    # Schema Registry
    "EventSchemaRegistry",
    # Serialization
    "EventSerializer",
    "MigrationInfo",
    "SchemaInfo",
    "SerializationError",
    "VersionMismatchError",
    "create_child_envelope",
    "create_serializer",
    "deserialize_event",
    # Utility functions
    "get_event_category",
    "get_event_type_docstring",
    "get_frontend_event_types",
    "get_schema",
    "is_delta_event",
    "is_hitl_event",
    "is_terminal_event",
    "migrate_event",
    "serialize_event",
]
