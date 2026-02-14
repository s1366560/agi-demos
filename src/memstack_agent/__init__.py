"""memstack-agent - A lightweight, modular Agent framework.

This framework provides a four-layer architecture for building AI agents:
- L1: Tools - Atomic capabilities
- L2: Skills - Declarative tool compositions
- L3: SubAgents - Specialized autonomous agents
- L4: Agents - ReAct reasoning loop

Designed for progressive complexity from minimal to production-grade usage.
"""

__version__ = "0.1.0"

# Core exports
from memstack_agent.core.events import (
    ActEvent,
    AgentEvent,
    ErrorEvent,
    ObserveEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThoughtEvent,
)
from memstack_agent.core.types import (
    AgentContext,
    EventType,
    ProcessorState,
)
from memstack_agent.tools.converter import (
    function_to_tool,
    infer_type_schema,
)

# Tool exports
from memstack_agent.tools.protocol import (
    Tool,
    ToolDefinition,
    ToolMetadata,
)

__all__ = [
    # Core
    "AgentContext",
    "ProcessorState",
    "EventType",
    # Events
    "AgentEvent",
    "ThoughtEvent",
    "ActEvent",
    "ObserveEvent",
    "TextStartEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "ErrorEvent",
    # Tools
    "ToolDefinition",
    "Tool",
    "ToolMetadata",
    "function_to_tool",
    "infer_type_schema",
]
