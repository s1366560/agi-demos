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
    "ActEvent",
    # Core
    "AgentContext",
    # Events
    "AgentEvent",
    "ChatResponse",
    "ErrorEvent",
    "EventType",
    "LLMClient",
    "LLMConfig",
    "LiteLLMAdapter",
    # LLM
    "Message",
    "MessageRole",
    "ObserveEvent",
    "ProcessorState",
    "StreamChunk",
    "TextDeltaEvent",
    "TextEndEvent",
    "TextStartEvent",
    "ThoughtEvent",
    "Tool",
    "ToolCall",
    # Tools
    "ToolDefinition",
    "ToolMetadata",
    "Usage",
    "anthropic_config",
    "create_llm_client",
    "deepseek_config",
    "function_to_tool",
    "gemini_config",
    "infer_type_schema",
    "openai_config",
]
