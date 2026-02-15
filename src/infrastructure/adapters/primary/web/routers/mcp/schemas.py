"""MCP API schemas.

Pydantic models for MCP server management and tool operations.
"""

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

MCPServerTypeValues = Literal["stdio", "sse", "http", "websocket"]

# === Database MCP Server Schemas ===


class MCPServerCreate(BaseModel):
    """Schema for creating a new MCP server."""

    name: str = Field(..., min_length=1, max_length=200, description="Server name")
    description: Optional[str] = Field(None, description="Server description")
    server_type: MCPServerTypeValues = Field(
        ..., description="Transport type: stdio, sse, http, websocket"
    )
    transport_config: Dict[str, Any] = Field(..., description="Transport configuration")
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

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None)
    server_type: Optional[MCPServerTypeValues] = Field(None)
    transport_config: Optional[Dict[str, Any]] = Field(None)
    enabled: Optional[bool] = Field(None)

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
    project_id: Optional[str] = None
    name: str
    description: Optional[str]
    server_type: str
    transport_config: Dict[str, Any]
    enabled: bool
    discovered_tools: List[Dict[str, Any]]
    sync_error: Optional[str] = None
    last_sync_at: Optional[datetime]
    created_at: datetime
    updated_at: Optional[datetime]


class MCPServerTestResult(BaseModel):
    """Result of testing an MCP server connection."""

    success: bool
    message: str
    tools_discovered: int = 0
    connection_time_ms: float = 0.0
    errors: List[str] = Field(default_factory=list)


# === Tool Schemas ===


class MCPToolResponse(BaseModel):
    """Schema for MCP tool response."""

    name: str
    description: Optional[str]
    server_id: str
    server_name: str
    input_schema: Dict[str, Any]


class MCPToolCallRequest(BaseModel):
    """Schema for MCP tool call request."""

    server_id: str = Field(..., description="MCP server ID")
    tool_name: str = Field(..., description="Tool name to call")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")


class MCPToolCallResponse(BaseModel):
    """Schema for MCP tool call response."""

    result: Any
    is_error: bool = False
    error_message: Optional[str] = None
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
    last_sync_at: Optional[datetime] = None
    sync_error: Optional[str] = None
    tools_count: int = 0


class MCPHealthSummary(BaseModel):
    """Aggregated health summary for all MCP servers in a project."""

    total: int
    healthy: int
    degraded: int
    error: int
    disabled: int
    servers: List[MCPServerHealthStatus]
