"""Tool system for memstack-agent.

Provides:
- Tool protocol (Protocol-based interface)
- ToolDefinition (immutable data class)
- Function tool conversion
- Schema inference
"""

from memstack_agent.tools.converter import (
    function_to_tool,
    infer_type_schema,
)
from memstack_agent.tools.protocol import (
    Tool,
    ToolDefinition,
    ToolMetadata,
)

__all__ = [
    "Tool",
    "ToolDefinition",
    "ToolMetadata",
    "function_to_tool",
    "infer_type_schema",
]
