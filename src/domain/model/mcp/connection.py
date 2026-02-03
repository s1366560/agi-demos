"""
MCP Connection Domain Models.

Defines connection state and info value objects.
Consolidates definitions from:
- src/application/services/mcp_bridge_service.py (ConnectionState, MCPConnectionInfo)
- src/infrastructure/mcp/config.py (MCPStatusType, MCPStatus)
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from src.domain.model.mcp.tool import MCPToolSchema


class ConnectionState(str, Enum):
    """MCP connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    ERROR = "error"
    CLOSED = "closed"

    @property
    def is_active(self) -> bool:
        """Check if connection is in an active state."""
        return self in (ConnectionState.CONNECTED, ConnectionState.CONNECTING)


@dataclass
class ConnectionInfo:
    """
    MCP connection information.

    Captures the current state of a connection including
    timing information and discovered capabilities.
    """

    endpoint: str  # Connection endpoint (URL or command)
    state: ConnectionState = ConnectionState.DISCONNECTED
    connected_at: Optional[datetime] = None
    disconnected_at: Optional[datetime] = None
    last_activity_at: Optional[datetime] = None
    last_ping_at: Optional[datetime] = None
    tools: List[MCPToolSchema] = field(default_factory=list)
    server_info: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    reconnect_count: int = 0

    @property
    def is_connected(self) -> bool:
        """Check if currently connected."""
        return self.state == ConnectionState.CONNECTED

    @property
    def connection_duration_seconds(self) -> Optional[float]:
        """Get connection duration in seconds."""
        if not self.connected_at:
            return None
        end_time = self.disconnected_at or datetime.now()
        return (end_time - self.connected_at).total_seconds()

    def mark_connected(
        self,
        server_info: Optional[Dict[str, Any]] = None,
        tools: Optional[List[MCPToolSchema]] = None,
    ) -> "ConnectionInfo":
        """Create new instance marking as connected."""
        now = datetime.now()
        return ConnectionInfo(
            endpoint=self.endpoint,
            state=ConnectionState.CONNECTED,
            connected_at=now,
            last_activity_at=now,
            tools=tools or self.tools,
            server_info=server_info or self.server_info,
            reconnect_count=self.reconnect_count,
        )

    def mark_disconnected(self, error_message: Optional[str] = None) -> "ConnectionInfo":
        """Create new instance marking as disconnected."""
        now = datetime.now()
        state = ConnectionState.ERROR if error_message else ConnectionState.DISCONNECTED
        return ConnectionInfo(
            endpoint=self.endpoint,
            state=state,
            connected_at=self.connected_at,
            disconnected_at=now,
            last_activity_at=now,
            tools=self.tools,
            server_info=self.server_info,
            error_message=error_message,
            reconnect_count=self.reconnect_count,
        )

    def mark_activity(self) -> "ConnectionInfo":
        """Create new instance with updated activity timestamp."""
        return ConnectionInfo(
            endpoint=self.endpoint,
            state=self.state,
            connected_at=self.connected_at,
            disconnected_at=self.disconnected_at,
            last_activity_at=datetime.now(),
            last_ping_at=self.last_ping_at,
            tools=self.tools,
            server_info=self.server_info,
            error_message=self.error_message,
            reconnect_count=self.reconnect_count,
        )

    def increment_reconnect(self) -> "ConnectionInfo":
        """Create new instance with incremented reconnect count."""
        return ConnectionInfo(
            endpoint=self.endpoint,
            state=ConnectionState.RECONNECTING,
            connected_at=self.connected_at,
            disconnected_at=self.disconnected_at,
            last_activity_at=datetime.now(),
            tools=self.tools,
            server_info=self.server_info,
            error_message=self.error_message,
            reconnect_count=self.reconnect_count + 1,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "endpoint": self.endpoint,
            "state": self.state.value,
            "connected_at": self.connected_at.isoformat() if self.connected_at else None,
            "disconnected_at": self.disconnected_at.isoformat() if self.disconnected_at else None,
            "last_activity_at": (
                self.last_activity_at.isoformat() if self.last_activity_at else None
            ),
            "last_ping_at": self.last_ping_at.isoformat() if self.last_ping_at else None,
            "tool_count": len(self.tools),
            "server_info": self.server_info,
            "error_message": self.error_message,
            "reconnect_count": self.reconnect_count,
        }


@dataclass
class ConnectionMetrics:
    """
    MCP connection metrics for monitoring.

    Tracks connection health and performance metrics.
    """

    total_connections: int = 0
    successful_connections: int = 0
    failed_connections: int = 0
    total_reconnects: int = 0
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    average_latency_ms: float = 0.0
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None

    def record_connection_success(self) -> None:
        """Record a successful connection."""
        self.total_connections += 1
        self.successful_connections += 1

    def record_connection_failure(self, error: str) -> None:
        """Record a failed connection."""
        self.total_connections += 1
        self.failed_connections += 1
        self.last_error = error
        self.last_error_at = datetime.now()

    def record_tool_call(self, success: bool, latency_ms: float) -> None:
        """Record a tool call result."""
        self.total_tool_calls += 1
        if success:
            self.successful_tool_calls += 1
        else:
            self.failed_tool_calls += 1

        # Update moving average latency
        if self.average_latency_ms == 0:
            self.average_latency_ms = latency_ms
        else:
            # Exponential moving average with alpha=0.1
            self.average_latency_ms = 0.9 * self.average_latency_ms + 0.1 * latency_ms

    @property
    def connection_success_rate(self) -> float:
        """Get connection success rate (0.0 to 1.0)."""
        if self.total_connections == 0:
            return 0.0
        return self.successful_connections / self.total_connections

    @property
    def tool_call_success_rate(self) -> float:
        """Get tool call success rate (0.0 to 1.0)."""
        if self.total_tool_calls == 0:
            return 0.0
        return self.successful_tool_calls / self.total_tool_calls

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for monitoring."""
        return {
            "total_connections": self.total_connections,
            "successful_connections": self.successful_connections,
            "failed_connections": self.failed_connections,
            "connection_success_rate": self.connection_success_rate,
            "total_reconnects": self.total_reconnects,
            "total_tool_calls": self.total_tool_calls,
            "successful_tool_calls": self.successful_tool_calls,
            "failed_tool_calls": self.failed_tool_calls,
            "tool_call_success_rate": self.tool_call_success_rate,
            "average_latency_ms": self.average_latency_ms,
            "last_error": self.last_error,
            "last_error_at": self.last_error_at.isoformat() if self.last_error_at else None,
        }
