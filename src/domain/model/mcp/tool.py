"""
MCP Tool Domain Models.

Defines the MCPTool entity, schema, and result value objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class MCPToolSchema:
    """
    MCP tool schema definition.

    Describes a tool's interface including its name, description,
    and JSON Schema for input parameters.
    """

    name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPToolSchema":
        """Create from dictionary (MCP protocol format)."""
        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            input_schema=data.get("inputSchema", data.get("input_schema", {})),
        )


@dataclass
class MCPToolResult:
    """
    MCP tool execution result.

    Contains the output of a tool call, including content,
    error status, and optional metadata/artifacts.
    """

    content: List[Dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    error_message: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    artifact: Optional[Dict[str, Any]] = None  # For export_artifact tool results
    execution_time_ms: Optional[int] = None

    @classmethod
    def success(
        cls,
        content: List[Dict[str, Any]],
        execution_time_ms: Optional[int] = None,
        artifact: Optional[Dict[str, Any]] = None,
    ) -> "MCPToolResult":
        """Create a successful result."""
        return cls(
            content=content,
            is_error=False,
            execution_time_ms=execution_time_ms,
            artifact=artifact,
        )

    @classmethod
    def error(
        cls,
        error_message: str,
        content: Optional[List[Dict[str, Any]]] = None,
        execution_time_ms: Optional[int] = None,
    ) -> "MCPToolResult":
        """Create an error result."""
        return cls(
            content=content or [{"type": "text", "text": error_message}],
            is_error=True,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPToolResult":
        """Create from dictionary (MCP protocol format)."""
        return cls(
            content=data.get("content", []),
            is_error=data.get("isError", data.get("is_error", False)),
            error_message=data.get("error_message"),
            metadata=data.get("metadata"),
            artifact=data.get("artifact"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "content": self.content,
            "is_error": self.is_error,
        }
        if self.error_message:
            result["error_message"] = self.error_message
        if self.metadata:
            result["metadata"] = self.metadata
        if self.artifact:
            result["artifact"] = self.artifact
        if self.execution_time_ms is not None:
            result["execution_time_ms"] = self.execution_time_ms
        return result

    def get_text_content(self) -> str:
        """Extract text content from result."""
        texts = []
        for item in self.content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
                else:
                    texts.append(str(item))
            else:
                texts.append(str(item))
        return "\n".join(texts)


@dataclass
class MCPTool:
    """
    MCP Tool entity.

    Represents a tool provided by an MCP server, combining
    the schema definition with server context.
    """

    server_id: str
    server_name: str
    schema: MCPToolSchema
    enabled: bool = True

    @property
    def name(self) -> str:
        """Get tool name."""
        return self.schema.name

    @property
    def full_name(self) -> str:
        """Get full tool name with server prefix (mcp__{server}__{tool})."""
        clean_server = self.server_name.replace("-", "_")
        return f"mcp__{clean_server}__{self.schema.name}"

    @property
    def description(self) -> str:
        """Get tool description."""
        return self.schema.description or f"MCP tool {self.name} from {self.server_name}"

    @property
    def input_schema(self) -> Dict[str, Any]:
        """Get tool input schema."""
        return self.schema.input_schema

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "server_id": self.server_id,
            "server_name": self.server_name,
            "name": self.name,
            "full_name": self.full_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "enabled": self.enabled,
        }


@dataclass
class MCPToolCallRequest:
    """
    MCP tool call request.

    Encapsulates all information needed to execute a tool call.
    """

    tool_name: str
    arguments: Dict[str, Any] = field(default_factory=dict)
    timeout: Optional[int] = None  # milliseconds
    request_id: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "timeout": self.timeout,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
        }
