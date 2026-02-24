"""
MCP Sandbox Instance - Data class for sandbox state.

Defines the MCPSandboxInstance data class that extends SandboxInstance
with MCP-specific attributes.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from src.domain.ports.services.sandbox_port import SandboxInstance, SandboxStatus


@dataclass
class MCPSandboxInstance(SandboxInstance):
    """Extended sandbox instance with MCP client and service ports.

    This class represents a running sandbox container with MCP WebSocket
    server, including connection state and service endpoints.

    Attributes:
        mcp_client: Active MCP WebSocket client connection
        websocket_url: WebSocket URL for MCP protocol
        mcp_port: Host port mapped to container MCP port
        desktop_port: Host port mapped to container desktop (noVNC) port
        terminal_port: Host port mapped to container terminal (ttyd) port
        desktop_url: Full URL for desktop access
        terminal_url: Full URL for terminal access
        tools_cache: Cached list of available MCP tools
        last_tool_refresh: Timestamp of last tool list refresh
    """

    # MCP WebSocket client (lazy import to avoid circular deps)
    mcp_client: Any | None = None
    websocket_url: str | None = None

    # Service ports on host
    mcp_port: int | None = None
    desktop_port: int | None = None
    terminal_port: int | None = None

    # Service URLs
    desktop_url: str | None = None
    terminal_url: str | None = None

    # Tool caching
    tools_cache: list[dict[str, Any]] = field(default_factory=list)
    last_tool_refresh: datetime | None = None

    @property
    def is_mcp_connected(self) -> bool:
        """Check if MCP client is connected."""
        return self.mcp_client is not None and getattr(self.mcp_client, "connected", False)

    @property
    def allocated_ports(self) -> list[int]:
        """Get list of all allocated ports."""
        ports = []
        if self.mcp_port:
            ports.append(self.mcp_port)
        if self.desktop_port:
            ports.append(self.desktop_port)
        if self.terminal_port:
            ports.append(self.terminal_port)
        return ports

    @property
    def project_id(self) -> str | None:
        """Get project ID from labels."""
        return self.labels.get("memstack.project_id") or self.labels.get("memstack.project.id")

    @property
    def tenant_id(self) -> str | None:
        """Get tenant ID from labels."""
        return self.labels.get("memstack.tenant_id") or self.labels.get("memstack.tenant.id")

    def to_dict(self) -> dict[str, Any]:
        """Convert instance to dictionary for API responses."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "status": self.status.value if isinstance(self.status, SandboxStatus) else self.status,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity_at": self.last_activity_at.isoformat()
            if self.last_activity_at
            else None,
            "websocket_url": self.websocket_url,
            "mcp_port": self.mcp_port,
            "desktop_port": self.desktop_port,
            "terminal_port": self.terminal_port,
            "desktop_url": self.desktop_url,
            "terminal_url": self.terminal_url,
            "is_mcp_connected": self.is_mcp_connected,
            "tools_count": len(self.tools_cache),
        }


@dataclass
class SandboxResourceUsage:
    """Resource usage statistics for a sandbox."""

    memory_mb: float = 0.0
    cpu_percent: float = 0.0
    disk_mb: float = 0.0
    network_rx_bytes: int = 0
    network_tx_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "memory_mb": self.memory_mb,
            "cpu_percent": self.cpu_percent,
            "disk_mb": self.disk_mb,
            "network_rx_bytes": self.network_rx_bytes,
            "network_tx_bytes": self.network_tx_bytes,
        }


@dataclass
class SandboxPorts:
    """Container port allocation."""

    mcp_port: int
    desktop_port: int
    terminal_port: int

    def as_list(self) -> list[int]:
        """Get all ports as list."""
        return [self.mcp_port, self.desktop_port, self.terminal_port]
