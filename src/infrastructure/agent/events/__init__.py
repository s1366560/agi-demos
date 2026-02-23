"""Events package for ReActAgent SSE streaming.

REFACTORED: This package now uses AgentEventType from src.domain.events.types
as the single source of truth. EventType is provided as a deprecated alias.
"""

# Re-export unified type for explicit access
from src.domain.events.types import AgentEventType
from src.infrastructure.agent.events.converter import (
    EventConverter,
    SkillLike,
    get_event_converter,
    set_event_converter,
)
from src.infrastructure.agent.events.event_mapper import (
    AgentDomainEvent,
    EventBus,
    EventMapper,
    EventType,  # Deprecated alias for AgentEventType
    SSEEvent,
    get_event_bus,
    set_event_bus,
)

__all__ = [
    # Event types (unified)
    "AgentEventType",  # Preferred
    "EventType",  # Deprecated alias for backward compatibility
    # SSE models
    "SSEEvent",
    "AgentDomainEvent",
    # Event Mapper (legacy)
    "EventMapper",
    "EventBus",
    "get_event_bus",
    "set_event_bus",
    # Event Converter (new unified converter)
    "EventConverter",
    "get_event_converter",
    "set_event_converter",
    "SkillLike",
]
