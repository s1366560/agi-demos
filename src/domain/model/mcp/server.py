"""
MCP Server Domain Models.

Defines the MCPServer entity, configuration, and status value objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.model.mcp.transport import TransportConfig, TransportType


class MCPServerStatusType(str, Enum):
    """MCP server connection status types."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    FAILED = "failed"
    DISABLED = "disabled"
    NEEDS_AUTH = "needs_auth"


@dataclass(frozen=True)
class MCPServerStatus:
    """
    MCP server status value object.

    Represents the current state of an MCP server connection.
    Immutable to ensure status snapshots are consistent.
    """

    status: MCPServerStatusType
    connected: bool = False
    tool_count: int = 0
    server_info: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    last_check_at: Optional[datetime] = None

    @classmethod
    def connected_status(
        cls,
        tool_count: int = 0,
        server_info: Optional[Dict[str, Any]] = None,
    ) -> "MCPServerStatus":
        """Create a connected status."""
        return cls(
            status=MCPServerStatusType.CONNECTED,
            connected=True,
            tool_count=tool_count,
            server_info=server_info,
            last_check_at=datetime.now(),
        )

    @classmethod
    def disconnected_status(cls) -> "MCPServerStatus":
        """Create a disconnected status."""
        return cls(
            status=MCPServerStatusType.DISCONNECTED,
            connected=False,
            last_check_at=datetime.now(),
        )

    @classmethod
    def failed_status(cls, error: str) -> "MCPServerStatus":
        """Create a failed status with error message."""
        return cls(
            status=MCPServerStatusType.FAILED,
            connected=False,
            error=error,
            last_check_at=datetime.now(),
        )

    @classmethod
    def connecting_status(cls) -> "MCPServerStatus":
        """Create a connecting status."""
        return cls(
            status=MCPServerStatusType.CONNECTING,
            connected=False,
            last_check_at=datetime.now(),
        )


@dataclass(frozen=True)
class MCPServerConfig:
    """
    MCP server configuration.

    Contains all settings needed to connect to an MCP server,
    supporting multiple transport types (stdio, http, sse, websocket).
    """

    server_name: str
    tenant_id: str
    transport_type: TransportType = TransportType.LOCAL
    enabled: bool = True

    # Local (stdio) transport config
    command: Optional[List[str]] = None
    environment: Optional[Dict[str, str]] = None

    # Remote transport config (HTTP/SSE/WebSocket)
    url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None

    # WebSocket specific config
    heartbeat_interval: int = 30  # seconds
    reconnect_attempts: int = 3

    # Common config
    timeout: int = 30000  # milliseconds

    def __post_init__(self):
        """Validate configuration based on transport type."""
        if self.transport_type == TransportType.LOCAL:
            if not self.command:
                raise ValueError("Command is required for local transport")
        elif self.transport_type in (
            TransportType.HTTP,
            TransportType.SSE,
            TransportType.WEBSOCKET,
        ):
            if not self.url:
                raise ValueError(f"URL is required for {self.transport_type.value} transport")

    def to_transport_config(self) -> TransportConfig:
        """Convert to TransportConfig value object."""
        return TransportConfig(
            transport_type=self.transport_type,
            command=self.command,
            environment=self.environment,
            url=self.url,
            headers=self.headers,
            timeout=self.timeout,
            heartbeat_interval=self.heartbeat_interval,
            reconnect_attempts=self.reconnect_attempts,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "server_name": self.server_name,
            "tenant_id": self.tenant_id,
            "transport_type": self.transport_type.value,
            "enabled": self.enabled,
            "command": self.command,
            "environment": self.environment,
            "url": self.url,
            "headers": self.headers,
            "heartbeat_interval": self.heartbeat_interval,
            "reconnect_attempts": self.reconnect_attempts,
            "timeout": self.timeout,
        }


@dataclass
class MCPServer:
    """
    MCP Server entity.

    Represents an MCP server with its configuration, status, and discovered tools.
    This is the aggregate root for MCP server management.
    """

    id: str
    tenant_id: str
    name: str
    project_id: Optional[str] = None
    description: Optional[str] = None

    # Flat DB-column fields used by repository and routers
    server_type: Optional[str] = None
    transport_config: Optional[Dict[str, Any]] = None
    enabled: bool = True
    discovered_tools: List[Any] = field(default_factory=list)
    sync_error: Optional[str] = None
    last_sync_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # Rich typed fields (optional, for higher-level consumers)
    config: Optional[MCPServerConfig] = None
    status: MCPServerStatus = field(default_factory=MCPServerStatus.disconnected_status)
    workflow_id: Optional[str] = None  # Temporal workflow ID if managed by Temporal

    def update_status(self, new_status: MCPServerStatus) -> None:
        """Update server status."""
        self.status = new_status

    def update_tools(
        self,
        tools: List[Any],
        sync_time: Optional[datetime] = None,
    ) -> None:
        """Update discovered tools and sync timestamp."""
        self.discovered_tools = tools
        self.last_sync_at = sync_time or datetime.now()

    @property
    def is_connected(self) -> bool:
        """Check if server is currently connected."""
        return self.status.connected

    @property
    def tool_count(self) -> int:
        """Get number of discovered tools."""
        return len(self.discovered_tools)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "server_type": self.server_type,
            "transport_config": self.transport_config,
            "enabled": self.enabled,
            "discovered_tools": self.discovered_tools,
            "sync_error": self.sync_error,
            "status": self.status.status.value,
            "connected": self.status.connected,
            "tool_count": self.tool_count,
            "server_info": self.status.server_info,
            "error": self.status.error,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "workflow_id": self.workflow_id,
        }
