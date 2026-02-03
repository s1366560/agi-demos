"""MCP API schemas.

Pydantic models for MCP server management and tool operations.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# === Database MCP Server Schemas ===


class MCPServerCreate(BaseModel):
    """Schema for creating a new MCP server."""

    name: str = Field(..., min_length=1, max_length=200, description="Server name")
    description: Optional[str] = Field(None, description="Server description")
    server_type: str = Field(..., description="Transport type: stdio, sse, http, websocket")
    transport_config: Dict[str, Any] = Field(..., description="Transport configuration")
    enabled: bool = Field(True, description="Whether server is enabled")


class MCPServerUpdate(BaseModel):
    """Schema for updating an MCP server."""

    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = Field(None)
    server_type: Optional[str] = Field(None)
    transport_config: Optional[Dict[str, Any]] = Field(None)
    enabled: Optional[bool] = Field(None)


class MCPServerResponse(BaseModel):
    """Schema for MCP server response."""

    id: str
    tenant_id: str
    name: str
    description: Optional[str]
    server_type: str
    transport_config: Dict[str, Any]
    enabled: bool
    discovered_tools: List[Dict[str, Any]]
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


# === Temporal MCP Schemas ===


class TemporalMCPConnectRequest(BaseModel):
    """Request schema for starting a Temporal MCP server workflow."""

    server_name: str = Field(..., description="Unique name for this MCP server")
    transport_type: str = Field("local", description="Transport type: 'local', 'http', or 'sse'")

    # Local transport config
    command: Optional[List[str]] = Field(None, description="Command for local MCP server")
    environment: Optional[Dict[str, str]] = Field(None, description="Environment variables")

    # Remote transport config
    url: Optional[str] = Field(None, description="URL for remote MCP server")
    headers: Optional[Dict[str, str]] = Field(None, description="HTTP headers")

    # Common settings
    timeout: int = Field(30000, description="Timeout in milliseconds")


class TemporalMCPStatusResponse(BaseModel):
    """Response schema for Temporal MCP server status."""

    server_name: str
    tenant_id: str
    connected: bool = False
    tool_count: int = 0
    error: Optional[str] = None
    workflow_id: Optional[str] = None


class TemporalMCPToolInfo(BaseModel):
    """Information about an MCP tool from Temporal."""

    name: str
    server_name: str
    description: Optional[str] = None
    input_schema: Dict[str, Any] = Field(default_factory=dict)


class TemporalMCPToolCallRequest(BaseModel):
    """Request schema for calling a Temporal MCP tool."""

    tool_name: str = Field(..., description="Name of the tool to call")
    arguments: Dict[str, Any] = Field(default_factory=dict, description="Tool arguments")
    timeout: Optional[int] = Field(None, description="Timeout in milliseconds")


class TemporalMCPToolCallResponse(BaseModel):
    """Response schema for Temporal MCP tool call."""

    content: List[Dict[str, Any]]
    is_error: bool = False
    error_message: Optional[str] = None
    execution_time_ms: float
