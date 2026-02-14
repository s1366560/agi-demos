"""Tool protocol and definitions for memstack-agent.

This module defines the Tool interface using Python's Protocol for
flexible implementation. Tools can be:
- Functions decorated with @tool
- Classes implementing the Tool protocol
- Lambda functions (via conversion)

Key design:
- Protocol-based (duck typing friendly)
- Immutable data classes for configuration
- Async-first execution model
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Protocol, runtime_checkable


@runtime_checkable
class Tool(Protocol):
    """Protocol for tool implementations.

    Any object implementing this interface can be used as a tool:
    - Async execute method with **kwargs
    - Readable name and description
    - JSON Schema parameter definition

    Example:
        class MyTool:
            name = "my_tool"
            description = "Does something"

            async def execute(self, **kwargs):
                return "result"
    """

    @property
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        ...

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with given arguments.

        Args:
            **kwargs: Tool-specific arguments

        Returns:
            Tool execution result (will be serialized to string)

        Raises:
            Exception: If tool execution fails
        """
        ...

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Get JSON Schema for tool parameters.

        Returns:
            JSON Schema dict describing parameters
        """
        ...

    @property
    def permission(self) -> Optional[str]:
        """Optional permission required to use this tool.

        Returns:
            Permission string or None if no permission required
        """
        ...

    @property
    def metadata(self) -> "ToolMetadata":
        """Additional tool metadata."""
        ...


@dataclass(frozen=True, kw_only=True)
class ToolMetadata:
    """Immutable metadata for tools.

    Contains optional metadata that controls tool behavior:
    - Tags for categorization
    - Whether tool is visible to LLM
    - Custom execution timeout
    - UI rendering hints
    """

    tags: List[str] = field(default_factory=list)
    visible_to_model: bool = True
    timeout_seconds: Optional[int] = None
    ui_category: Optional[str] = None  # For UI grouping
    ui_component: Optional[str] = None  # For custom UI rendering
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ToolDefinition:
    """Immutable definition of a tool for LLM consumption.

    This is the core data structure passed to LLMs in tool definitions.
    It wraps a Tool with additional execution context:
    - JSON Schema for parameters
    - Async execute callable
    - Optional permission requirement
    - Reference to original tool instance

    The execute field is a closure that wraps the original tool's
    execute method, allowing uniform invocation regardless of tool type.
    """

    name: str
    description: str
    parameters: Dict[str, Any]
    execute: Callable[..., Any]
    permission: Optional[str] = None
    metadata: ToolMetadata = field(default_factory=ToolMetadata)
    _tool_instance: Any = field(default=None, repr=False)

    def to_openai_format(self) -> Dict[str, Any]:
        """Convert to OpenAI tool format.

        Returns:
            Dict in OpenAI function calling format:
            {
                "type": "function",
                "function": {
                    "name": "...",
                    "description": "...",
                    "parameters": {...}
                }
            }
        """
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_format(self) -> Dict[str, Any]:
        """Convert to Anthropic tool format.

        Returns:
            Dict in Anthropic tool format:
            {
                "name": "...",
                "description": "...",
                "input_schema": {...}
            }
        """
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert to generic dictionary representation.

        Returns:
            Dict with name, description, parameters, permission
        """
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
            "permission": self.permission,
            "metadata": {
                "tags": self.metadata.tags,
                "visible_to_model": self.metadata.visible_to_model,
                "ui_category": self.metadata.ui_category,
            },
        }


class SimpleTool:
    """Simple base class for tool implementations.

    Provides a straightforward way to create tools by extending
    this class and defining name, description, and execute.

    Example:
        class Calculator(SimpleTool):
            name = "calculator"
            description = "Performs calculations"

            async def execute(self, expression: str) -> str:
                return str(eval(expression))
    """

    # Class attributes (override in subclasses)
    name: str
    description: str

    @property
    def permission(self) -> Optional[str]:
        """Permission required to use this tool."""
        return None

    @property
    def metadata(self) -> ToolMetadata:
        """Tool metadata."""
        return ToolMetadata()

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool. Must be implemented by subclasses."""
        raise NotImplementedError(f"{self.name}.execute() not implemented")

    def get_parameters_schema(self) -> Dict[str, Any]:
        """Default empty parameters schema. Override for custom schemas."""
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }


__all__ = [
    "Tool",
    "ToolDefinition",
    "ToolMetadata",
    "SimpleTool",
]
