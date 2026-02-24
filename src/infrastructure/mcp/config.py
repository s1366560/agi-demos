"""
MCP Configuration Models.

Defines Pydantic models for MCP server configuration.
Supports both local (stdio) and remote (HTTP/SSE) connection types.

Reference: OpenCode config/config.ts McpLocal/McpRemote schemas

MIGRATION NOTE:
===============
These Pydantic models are being migrated to domain models.
New code should use:
- src.domain.model.mcp.transport.TransportConfig (replaces McpLocalConfig, McpRemoteConfig)
- src.domain.model.mcp.transport.TransportType (replaces type field)
- src.domain.model.mcp.server.MCPServer (unified server entity)

The models in this file are kept for backward compatibility with
existing database records and API contracts.
"""

from enum import Enum
from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class McpLocalConfig(BaseModel):
    """
    Configuration for local MCP server (stdio transport).

    Example:
        {
            "type": "local",
            "command": ["docker", "run", "-i", "--rm", "mcp/fetch"],
            "environment": {"DEBUG": "true"},
            "enabled": true,
            "timeout": 30000
        }
    """

    type: Literal["local"] = "local"
    command: list[str] = Field(..., description="Command and arguments to run the MCP server")
    environment: dict[str, str] | None = Field(
        default=None, description="Environment variables to set when running the MCP server"
    )
    enabled: bool = Field(default=True, description="Enable or disable the MCP server on startup")
    timeout: int = Field(
        default=30000, description="Timeout in ms for MCP server requests (default: 30s)"
    )


class McpOAuthConfig(BaseModel):
    """
    OAuth configuration for remote MCP servers.

    Supports RFC 7591 dynamic client registration when client_id is not provided.
    """

    client_id: str | None = Field(
        default=None,
        description="OAuth client ID. If not provided, dynamic client registration will be attempted",
    )
    client_secret: str | None = Field(
        default=None, description="OAuth client secret (if required by the authorization server)"
    )
    scope: str | None = Field(
        default=None, description="OAuth scopes to request during authorization"
    )


class McpRemoteConfig(BaseModel):
    """
    Configuration for remote MCP server (HTTP/SSE transport).

    Example:
        {
            "type": "remote",
            "url": "https://api.example.com/mcp",
            "headers": {"Authorization": "Bearer token"},
            "oauth": {"client_id": "my-app"},
            "enabled": true,
            "timeout": 30000
        }
    """

    type: Literal["remote"] = "remote"
    url: str = Field(..., description="URL of the remote MCP server")
    headers: dict[str, str] | None = Field(
        default=None, description="Headers to send with the request"
    )
    oauth: McpOAuthConfig | Literal[False] | None = Field(
        default=None,
        description="OAuth authentication configuration. Set to false to disable OAuth auto-detection",
    )
    enabled: bool = Field(default=True, description="Enable or disable the MCP server on startup")
    timeout: int = Field(
        default=30000, description="Timeout in ms for MCP server requests (default: 30s)"
    )


class McpWebSocketConfig(BaseModel):
    """
    Configuration for WebSocket MCP server transport.

    WebSocket provides bidirectional communication, persistent connections,
    and cross-network support for remote sandbox operations.

    Example:
        {
            "type": "websocket",
            "url": "ws://sandbox:8765",
            "headers": {"Authorization": "Bearer token"},
            "enabled": true,
            "timeout": 30000,
            "heartbeat_interval": 30,
            "reconnect_attempts": 3
        }
    """

    type: Literal["websocket"] = "websocket"
    url: str = Field(..., description="WebSocket URL (ws:// or wss://)")
    headers: dict[str, str] | None = Field(
        default=None, description="HTTP headers for WebSocket connection upgrade"
    )
    enabled: bool = Field(default=True, description="Enable or disable the MCP server on startup")
    timeout: int = Field(default=30000, description="Request timeout in ms (default: 30s)")
    heartbeat_interval: int | None = Field(
        default=None,
        description="WebSocket ping interval in seconds. None disables heartbeat "
        "(recommended to prevent PONG timeout killing long-running tool calls)",
    )
    reconnect_attempts: int = Field(
        default=3, description="Max reconnection attempts on connection loss (default: 3)"
    )


# Union type for MCP configuration
McpConfig = Union[McpLocalConfig, McpRemoteConfig, McpWebSocketConfig]


class MCPStatusType(str, Enum):
    """MCP connection status types."""

    CONNECTED = "connected"
    DISABLED = "disabled"
    FAILED = "failed"
    NEEDS_AUTH = "needs_auth"
    NEEDS_CLIENT_REGISTRATION = "needs_client_registration"
    CONNECTING = "connecting"


class MCPStatus(BaseModel):
    """
    MCP server connection status.

    Reference: OpenCode MCP.Status discriminated union
    """

    status: MCPStatusType
    error: str | None = None

    @classmethod
    def connected(cls) -> "MCPStatus":
        return cls(status=MCPStatusType.CONNECTED)

    @classmethod
    def disabled(cls) -> "MCPStatus":
        return cls(status=MCPStatusType.DISABLED)

    @classmethod
    def failed(cls, error: str) -> "MCPStatus":
        return cls(status=MCPStatusType.FAILED, error=error)

    @classmethod
    def needs_auth(cls) -> "MCPStatus":
        return cls(status=MCPStatusType.NEEDS_AUTH)

    @classmethod
    def needs_client_registration(cls, error: str) -> "MCPStatus":
        return cls(status=MCPStatusType.NEEDS_CLIENT_REGISTRATION, error=error)

    @classmethod
    def connecting(cls) -> "MCPStatus":
        return cls(status=MCPStatusType.CONNECTING)


class MCPToolDefinition(BaseModel):
    """
    MCP tool definition returned by listTools().

    Reference: @modelcontextprotocol/sdk MCPToolDef

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolSchema instead.
    Kept for backward compatibility with existing API contracts.
    """

    name: str
    description: str | None = None
    inputSchema: dict[str, Any] = Field(default_factory=dict)


class MCPToolResult(BaseModel):
    """
    Result from MCP tool execution.

    Reference: @modelcontextprotocol/sdk CallToolResult

    DEPRECATED: Use src.domain.model.mcp.tool.MCPToolResult instead.
    Kept for backward compatibility with existing API contracts.
    """

    content: list[dict[str, Any]] = Field(default_factory=list)
    isError: bool = False
    metadata: dict[str, Any] | None = None
