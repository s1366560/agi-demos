"""
MCP Tool Domain Models.

Defines the MCPTool entity, schema, and result value objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast


@dataclass(frozen=True)
class MCPToolSchema:
    """
    MCP tool schema definition.

    Describes a tool's interface including its name, description,
    and JSON Schema for input parameters.
    """

    name: str
    description: str | None = None
    input_schema: dict[str, Any] = field(default_factory=dict)
    ui_metadata: dict[str, Any] | None = None

    @property
    def has_ui(self) -> bool:
        """Check if this tool declares an MCP App UI via _meta.ui.

        Accepts any non-empty resourceUri scheme (ui://, mcp-app://, etc.)."""
        return (
            self.ui_metadata is not None
            and "resourceUri" in self.ui_metadata
            and bool(self.ui_metadata["resourceUri"])
        )

    @property
    def resource_uri(self) -> str | None:
        """Get the resource URI if present (any scheme: ui://, mcp-app://, etc.)."""
        if self.ui_metadata:
            return self.ui_metadata.get("resourceUri")
        return None

    @property
    def visibility(self) -> list[str]:
        """Get visibility from _meta.ui.visibility (SEP-1865).

        Returns ["model", "app"] if not specified (default per spec).
        "model" = visible to and callable by the LLM agent.
        "app" = callable by the MCP App UI only.
        """
        if self.ui_metadata:
            return cast(list[str], self.ui_metadata.get("visibility", ["model", "app"]))
        return ["model", "app"]

    @property
    def is_model_visible(self) -> bool:
        """Whether this tool should be included in the LLM's tool list."""
        return "model" in self.visibility

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.input_schema,
        }
        if self.ui_metadata:
            result["_meta"] = {"ui": self.ui_metadata}
        return result

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPToolSchema":
        """Create from dictionary (MCP protocol format)."""
        ui_metadata = None
        meta = data.get("_meta")
        if meta and isinstance(meta, dict):
            ui_metadata = meta.get("ui")
            # SEP-1865: Fallback for deprecated flat format _meta["ui/resourceUri"]
            if not ui_metadata:
                deprecated_uri = meta.get("ui/resourceUri")
                if deprecated_uri:
                    ui_metadata = {"resourceUri": deprecated_uri}
        return cls(
            name=data.get("name", ""),
            description=data.get("description"),
            input_schema=data.get("inputSchema", data.get("input_schema", {})),
            ui_metadata=ui_metadata,
        )


@dataclass
class MCPToolResult:
    """
    MCP tool execution result.

    Contains the output of a tool call, including content,
    error status, and optional metadata/artifacts.
    """

    content: list[dict[str, Any]] = field(default_factory=list)
    is_error: bool = False
    error_message: str | None = None
    metadata: dict[str, Any] | None = None
    artifact: dict[str, Any] | None = None  # For export_artifact tool results
    execution_time_ms: int | None = None

    @classmethod
    def success(
        cls,
        content: list[dict[str, Any]],
        execution_time_ms: int | None = None,
        artifact: dict[str, Any] | None = None,
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
        content: list[dict[str, Any]] | None = None,
        execution_time_ms: int | None = None,
    ) -> "MCPToolResult":
        """Create an error result."""
        return cls(
            content=content or [{"type": "text", "text": error_message}],
            is_error=True,
            error_message=error_message,
            execution_time_ms=execution_time_ms,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPToolResult":
        """Create from dictionary (MCP protocol format)."""
        return cls(
            content=data.get("content", []),
            is_error=data.get("isError", data.get("is_error", False)),
            error_message=data.get("error_message"),
            metadata=data.get("metadata"),
            artifact=data.get("artifact"),
        )

    def to_dict(self) -> dict[str, Any]:
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
                texts.append(str(item))  # type: ignore[unreachable]
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
    def input_schema(self) -> dict[str, Any]:
        """Get tool input schema."""
        return self.schema.input_schema

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        result = {
            "server_id": self.server_id,
            "server_name": self.server_name,
            "name": self.name,
            "full_name": self.full_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "enabled": self.enabled,
        }
        if self.schema.has_ui:
            result["_meta"] = {"ui": self.schema.ui_metadata}
        return result


@dataclass
class MCPToolCallRequest:
    """
    MCP tool call request.

    Encapsulates all information needed to execute a tool call.
    """

    tool_name: str
    arguments: dict[str, Any] = field(default_factory=dict)
    timeout: int | None = None  # milliseconds
    request_id: str | None = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "tool_name": self.tool_name,
            "arguments": self.arguments,
            "timeout": self.timeout,
            "request_id": self.request_id,
            "timestamp": self.timestamp.isoformat(),
        }
