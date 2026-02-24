"""Core types and abstractions for memstack-agent.

This module contains foundational types that have zero external dependencies:
- Enums for state and event types
- Data classes for context and configuration
- Protocol definitions for extensibility
"""

from memstack_agent.core.types import (
    AgentContext,
    EventCategory,
    EventType,
    ProcessorConfig,
    ProcessorState,
)

__all__ = [
    "AgentContext",
    "EventCategory",
    "EventType",
    "ProcessorConfig",
    "ProcessorState",
]
