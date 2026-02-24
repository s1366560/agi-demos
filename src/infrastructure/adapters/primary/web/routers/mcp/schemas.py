"""MCP API schemas.

Pydantic models for MCP server management and tool operations.
"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MCPServerTypeValues = Literal["stdio", "sse", "http", "websocket"]

# === Database MCP Server Schemas ===


class MCPServerCreate(BaseModel):
    """Schema for creating a new MCP server."""

    name: str = Field(..., min_length=1, max_length=200, description="Server name")
    description: str | None = Field(None, description="Server description")
    server_type: MCPServerTypeValues = Field(
        ..., description="Transport type: stdio, sse, http, websocket"
    )
    transport_config: dict[str, Any] = Field(..., description="Transport configuration")
    enabled: bool = Field(True, description="Whether server is enabled")
    project_id: str = Field(..., description="Project ID this server belongs to")

    @model_validator(mode="after")
    def validate_transport_config(self) -> "MCPServerCreate":
        """Validate transport_config has required fields for the given server_type."""
        cfg = self.transport_config
        if self.server_type == "stdio":
            if not cfg.get("command"):
                raise ValueError("stdio transport requires 'command' in transport_config")
        elif self.server_type in ("sse", "http", "websocket"):
            if not cfg.get("url"):
                raise ValueError(f"{self.server_type} transport requires 'url' in transport_config")
        return self


class MCPServerUpdate(BaseModel):
    """Schema for updating an MCP server."""

    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = Field(None)
    server_type: MCPServerTypeValues | None = Field(None)
    transport_config: dict[str, Any] | None = Field(None)
    enabled: bool | None = Field(None)

    @model_validator(mode="after")
    def validate_transport_config(self) -> "MCPServerUpdate":
        """Validate transport_config when both server_type and config are provided."""
        if self.server_type and self.transport_config:
            cfg = self.transport_config
            if self.server_type == "stdio":
                if not cfg.get("command"):
                    raise ValueError("stdio transport requires 'command' in transport_config")
            elif self.server_type in ("sse", "http", "websocket"):
                if not cfg.get("url"):
                    raise ValueError(
                        f"{self.server_type} transport requires 'url' in transport_config"
                    )
        return self


class MCPServerResponse(BaseModel):
    """Schema for MCP server response."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    tenant_id: str
    project_id: str | None = None
    name: str
    description: str | None
    server_type: str
    transport_config: dict[str, Any]
    enabled: bool
    runtime_status: str = "unknown"
    runtime_metadata: dict[str, Any] = Field(default_factory=dict)
    discovered_tools: list[dict[str, Any]]
    sync_error: str | None = None
    last_sync_at: datetime | None
    created_at: datetime
    updated_at: datetime | None


class MCPServerTestResult(BaseModel):
    """Result of testing an MCP server connection."""

    success: bool
    message: str
    tools_discovered: int = 0
    connection_time_ms: float = 0.0
    errors: list[str] = Field(default_factory=list)


class MCPReconcileResultResponse(BaseModel):
    """Result of project-level MCP reconcile."""

    project_id: str
    total_enabled_servers: int
    already_running: int
    restored: int
    failed: int


# === Tool Schemas ===


class MCPToolResponse(BaseModel):
    """Schema for MCP tool response."""

    name: str
    description: str | None
    server_id: str
    server_name: str
    input_schema: dict[str, Any]


class MCPToolCallRequest(BaseModel):
    """Schema for MCP tool call request."""

    server_id: str = Field(..., description="MCP server ID")
    tool_name: str = Field(..., description="Tool name to call")
    arguments: dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class MCPToolCallResponse(BaseModel):
    """Schema for MCP tool call response."""

    result: Any
    is_error: bool = False
    error_message: str | None = None
    execution_time_ms: float


class MCPToolListResponse(BaseModel):
    """Paginated list of MCP tools."""

    items: list[MCPToolResponse]
    total: int
    page: int
    per_page: int
    total_pages: int


# === Health Check Schemas ===


class MCPServerHealthStatus(BaseModel):
    """Health status for a single MCP server."""

    id: str
    name: str
    status: Literal["healthy", "degraded", "error", "disabled", "unknown"]
    enabled: bool
    last_sync_at: datetime | None = None
    sync_error: str | None = None
    tools_count: int = 0


class MCPHealthSummary(BaseModel):
    """Aggregated health summary for all MCP servers in a project."""

    total: int
    healthy: int
    degraded: int
    error: int
    disabled: int
    servers: list[MCPServerHealthStatus]
