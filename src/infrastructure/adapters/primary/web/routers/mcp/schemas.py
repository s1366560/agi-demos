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
    project_id: str = Field(..., description="Project ID this server belongs to")


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
