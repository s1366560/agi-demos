"""
MCP Server Domain Models.

Defines the MCPServer entity, configuration, and status value objects.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

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
    server_info: dict[str, Any] | None = None
    error: str | None = None
    last_check_at: datetime | None = None

    @classmethod
    def connected_status(
        cls,
        tool_count: int = 0,
        server_info: dict[str, Any] | None = None,
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
    command: list[str] | None = None
    environment: dict[str, str] | None = None

    # Remote transport config (HTTP/SSE/WebSocket)
    url: str | None = None
    headers: dict[str, str] | None = None

    # WebSocket specific config
    heartbeat_interval: int = 30  # seconds
    reconnect_attempts: int = 3

    # Common config
    timeout: int = 30000  # milliseconds

    def __post_init__(self) -> None:
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

    def to_dict(self) -> dict[str, Any]:
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
    project_id: str | None = None
    description: str | None = None

    # Flat DB-column fields used by repository and routers
    server_type: str | None = None
    transport_config: dict[str, Any] | None = None
    enabled: bool = True
    discovered_tools: list[Any] = field(default_factory=list)
    runtime_status: str = "unknown"
    runtime_metadata: dict[str, Any] = field(default_factory=dict)
    sync_error: str | None = None
    last_sync_at: datetime | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None

    # Rich typed fields (optional, for higher-level consumers)
    config: MCPServerConfig | None = None
    status: MCPServerStatus = field(default_factory=MCPServerStatus.disconnected_status)
    workflow_id: str | None = None  # Temporal workflow ID if managed by Temporal

    def update_status(self, new_status: MCPServerStatus) -> None:
        """Update server status."""
        self.status = new_status

    def update_tools(
        self,
        tools: list[Any],
        sync_time: datetime | None = None,
    ) -> None:
        """Update discovered tools and sync timestamp."""
        self.discovered_tools = tools
        self.last_sync_at = sync_time or datetime.now()

    def update_runtime(
        self,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update runtime status and metadata snapshot."""
        self.runtime_status = status
        if metadata:
            self.runtime_metadata = {**self.runtime_metadata, **metadata}

    @property
    def is_connected(self) -> bool:
        """Check if server is currently connected."""
        return self.status.connected

    @property
    def tool_count(self) -> int:
        """Get number of discovered tools."""
        return len(self.discovered_tools)

    def to_dict(self) -> dict[str, Any]:
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
            "runtime_status": self.runtime_status,
            "runtime_metadata": self.runtime_metadata,
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
