"""
Tool Port - Domain layer interface for agent tools.

Defines the contract for tools that can be used by the agent.
Tools implement this interface; infrastructure adapters handle
format conversion and execution.

This eliminates multiple format conversions by providing a single
source of truth for tool metadata.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class ToolPermission(str, Enum):
    """Standard tool permission levels."""

    READ = "read"  # Read-only operations
    WRITE = "write"  # Write operations (file, database)
    EXECUTE = "execute"  # Code execution
    NETWORK = "network"  # Network access
    ADMIN = "admin"  # Administrative operations


@dataclass
class ToolResult:
    """Standard result from tool execution.

    Attributes:
        output: Main output content
        success: Whether execution succeeded
        error: Error message if failed
        metadata: Additional metadata
        artifacts: Generated artifacts (files, images, etc.)
    """

    output: str
    success: bool = True
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)

    @staticmethod
    def ok(output: str, **metadata) -> "ToolResult":
        """Create a success result."""
        return ToolResult(output=output, success=True, metadata=metadata)

    @staticmethod
    def fail(error: str, output: str = "") -> "ToolResult":
        """Create a failure result."""
        return ToolResult(output=output, success=False, error=error)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "output": self.output,
            "success": self.success,
        }
        if self.error:
            result["error"] = self.error
        if self.metadata:
            result["metadata"] = self.metadata
        if self.artifacts:
            result["artifacts"] = self.artifacts
        return result


@dataclass
class ToolParameter:
    """Definition of a tool parameter.

    Attributes:
        name: Parameter name
        type: Parameter type (string, integer, boolean, array, object)
        description: Parameter description
        required: Whether parameter is required
        default: Default value if not provided
        enum: Allowed values for enum parameters
    """

    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] | None = None

    def to_json_schema(self) -> dict[str, Any]:
        """Convert to JSON Schema format."""
        schema = {
            "type": self.type,
            "description": self.description,
        }
        if self.enum:
            schema["enum"] = self.enum
        if self.default is not None:
            schema["default"] = self.default
        return schema


@runtime_checkable
class ToolPort(Protocol):
    """
    Protocol for agent tools.

    Tools that implement this protocol can be used by the ReAct agent.
    The protocol provides a clean interface that eliminates the need
    for multiple format conversions.

    Example:
        class WebSearchTool(ToolPort):
            @property
            def name(self) -> str:
                return "web_search"

            @property
            def description(self) -> str:
                return "Search the web for information"

            @property
            def parameters(self) -> List[ToolParameter]:
                return [
                    ToolParameter(
                        name="query",
                        type="string",
                        description="Search query",
                    )
                ]

            async def execute(self, **kwargs) -> ToolResult:
                query = kwargs["query"]
                results = await self._search(query)
                return ToolResult.ok(results)
    """

    @property
    def name(self) -> str:
        """Unique tool name."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        ...

    @property
    def parameters(self) -> list[ToolParameter]:
        """List of tool parameters."""
        ...

    @property
    def version(self) -> str:
        """Tool version (semver format)."""
        ...

    @property
    def permission_required(self) -> str | None:
        """Permission required to use this tool."""
        ...

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute the tool with given arguments.

        Args:
            **kwargs: Tool arguments as keyword arguments

        Returns:
            ToolResult with output or error
        """
        ...


class BaseTool:
    """
    Base implementation of ToolPort.

    Provides default implementations for common properties.
    Subclasses should override execute() and optionally other properties.

    Example:
        class MyTool(BaseTool):
            def __init__(self):
                super().__init__(
                    name="my_tool",
                    description="Does something useful",
                    parameters=[
                        ToolParameter("input", "string", "The input"),
                    ],
                )

            async def execute(self, **kwargs) -> ToolResult:
                return ToolResult.ok(f"Processed: {kwargs['input']}")
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: list[ToolParameter] | None = None,
        version: str = "1.0.0",
        permission_required: str | None = None,
    ) -> None:
        self._name = name
        self._description = description
        self._parameters = parameters or []
        self._version = version
        self._permission_required = permission_required

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> list[ToolParameter]:
        return self._parameters

    @property
    def version(self) -> str:
        return self._version

    @property
    def permission_required(self) -> str | None:
        return self._permission_required

    def get_parameters_schema(self) -> dict[str, Any]:
        """Get parameters as JSON Schema format."""
        properties = {}
        required = []

        for param in self._parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "type": "object",
            "properties": properties,
            "required": required,
        }

    def to_openai_format(self) -> dict[str, Any]:
        """Convert to OpenAI function calling format."""
        return {
            "type": "function",
            "function": {
                "name": self._name,
                "description": self._description,
                "parameters": self.get_parameters_schema(),
            },
        }

    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool. Override in subclasses."""
        raise NotImplementedError("Subclasses must implement execute()")
