"""Events package for ReActAgent SSE streaming."""

from src.infrastructure.agent.events.event_mapper import (
    EventType,
    SSEEvent,
    AgentDomainEvent,
    EventMapper,
    EventBus,
    get_event_bus,
    set_event_bus,
)
from src.infrastructure.agent.events.converter import (
    EventConverter,
    get_event_converter,
    set_event_converter,
    SkillLike,
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
