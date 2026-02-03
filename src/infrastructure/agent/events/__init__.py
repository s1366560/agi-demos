"""Events package for ReActAgent SSE streaming."""

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
    EventType,
    SSEEvent,
    get_event_bus,
    set_event_bus,
)

__all__ = [
    # Event types and models
    "EventType",
    "event_type",
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
