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

# LLM exports
from memstack_agent.llm import (
    ChatResponse,
    LiteLLMAdapter,
    LLMClient,
    LLMConfig,
    Message,
    MessageRole,
    StreamChunk,
    ToolCall,
    Usage,
    anthropic_config,
    create_llm_client,
    deepseek_config,
    gemini_config,
    openai_config,
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
    # LLM
    "Message",
    "MessageRole",
    "ToolCall",
    "Usage",
    "ChatResponse",
    "StreamChunk",
    "LLMConfig",
    "LLMClient",
    "LiteLLMAdapter",
    "create_llm_client",
    "anthropic_config",
    "openai_config",
    "gemini_config",
    "deepseek_config",
]
