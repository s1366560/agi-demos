"""Project-Sandbox association domain model.

This module defines the domain model for managing the lifecycle association
between Projects and their dedicated Sandbox instances.

Supports both cloud sandboxes (Docker containers managed by platform) and
local sandboxes (running on user's machine, connected via WebSocket tunnel).
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from src.domain.shared_kernel import Entity


class SandboxType(Enum):
    """Type of sandbox deployment."""

    CLOUD = "cloud"  # Server-managed Docker container (default)
    LOCAL = "local"  # User's local machine via WebSocket tunnel


class SandboxTransport(Enum):
    """Transport protocol for sandbox communication."""

    WEBSOCKET = "websocket"  # WebSocket connection (default for both cloud and local)
    STDIO = "stdio"  # Standard I/O (for local subprocess only)


@dataclass(frozen=True, kw_only=True)
class LocalSandboxConfig:
    """Configuration for local sandbox connection.

    Value object containing connection parameters for local sandboxes
    running on user's machine.

    Attributes:
        workspace_path: Absolute path to workspace directory on user's machine
        transport: Transport protocol (websocket or stdio)
        tunnel_url: Tunnel URL for WebSocket connection (e.g., wss://xxx.ngrok.io)
        host: Local host address (default: localhost)
        port: Local port number (default: 8765)
        auth_token: Authentication token for secure connection
    """

    workspace_path: str = "/workspace"
    transport: SandboxTransport = SandboxTransport.WEBSOCKET
    tunnel_url: Optional[str] = None  # For NAT traversal (ngrok/cloudflare)
    host: str = "localhost"
    port: int = 8765
    auth_token: Optional[str] = None

    def get_websocket_url(self) -> str:
        """Get the WebSocket URL for connection."""
        if self.tunnel_url:
            return self.tunnel_url
        protocol = "ws" if self.host in ("localhost", "127.0.0.1") else "wss"
        return f"{protocol}://{self.host}:{self.port}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "workspace_path": self.workspace_path,
            "transport": self.transport.value,
            "tunnel_url": self.tunnel_url,
            "host": self.host,
            "port": self.port,
            "auth_token": self.auth_token,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LocalSandboxConfig":
        """Create from dictionary."""
        transport = data.get("transport", "websocket")
        if isinstance(transport, str):
            transport = SandboxTransport(transport)
        return cls(
            workspace_path=data.get("workspace_path", "/workspace"),
            transport=transport,
            tunnel_url=data.get("tunnel_url"),
            host=data.get("host", "localhost"),
            port=data.get("port", 8765),
            auth_token=data.get("auth_token"),
        )


class ProjectSandboxStatus(Enum):
    """Status of a project-sandbox association.

    Simplified from 10 states to 4 essential states:
    - STARTING: Combines PENDING, CREATING, CONNECTING
    - RUNNING: Sandbox is running and healthy
    - ERROR: Combines UNHEALTHY, ERROR, DISCONNECTED
    - TERMINATED: Combines STOPPED, TERMINATED, ORPHAN

    Legacy status values are retained for backward compatibility.
    """

    # Simplified states (preferred)
    STARTING = "starting"  # Sandbox is being created or connecting
    RUNNING = "running"  # Sandbox is running and healthy
    ERROR = "error"  # Sandbox has an error (includes unhealthy, disconnected)
    TERMINATED = "terminated"  # Sandbox has been terminated

    # Legacy states (deprecated, mapped to simplified states)
    PENDING = "pending"  # Deprecated: Use STARTING
    CREATING = "creating"  # Deprecated: Use STARTING
    UNHEALTHY = "unhealthy"  # Deprecated: Use ERROR
    STOPPED = "stopped"  # Deprecated: Use TERMINATED
    CONNECTING = "connecting"  # Deprecated: Use STARTING
    DISCONNECTED = "disconnected"  # Deprecated: Use ERROR
    ORPHAN = "orphan"  # Deprecated: Use ERROR (with metadata flag)


@dataclass(kw_only=True)
class ProjectSandbox(Entity):
    """Project-Sandbox lifecycle association entity.

    Each project should have exactly one persistent sandbox that:
    - Is created on first use (lazy initialization)
    - Remains running until project deletion or manual termination
    - Can be auto-restarted if unhealthy
    - Provides isolated environment for project-specific operations

    Supports both cloud sandboxes (Docker containers) and local sandboxes
    (user's machine via WebSocket tunnel).

    Attributes:
        project_id: Associated project ID
        tenant_id: Tenant ID for scoping
        sandbox_id: Unique sandbox instance identifier
        sandbox_type: Type of sandbox (cloud or local)
        status: Current lifecycle status
        created_at: When the association was created
        started_at: When the sandbox container was started
        last_accessed_at: Last time the sandbox was used
        health_checked_at: Last health check timestamp
        error_message: Error description if in ERROR status
        metadata: Additional configuration and state
        local_config: Configuration for local sandbox (if sandbox_type is LOCAL)
    """

    project_id: str
    tenant_id: str
    sandbox_id: str
    sandbox_type: SandboxType = SandboxType.CLOUD
    status: ProjectSandboxStatus = ProjectSandboxStatus.STARTING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    last_accessed_at: datetime = field(default_factory=datetime.utcnow)
    health_checked_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    local_config: Optional[LocalSandboxConfig] = None

    def __post_init__(self) -> None:
        """Validate sandbox configuration."""
        if self.sandbox_type == SandboxType.LOCAL and self.local_config is None:
            # Initialize default local config if not provided
            object.__setattr__(self, "local_config", LocalSandboxConfig())

    def mark_accessed(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = datetime.utcnow()

    def mark_healthy(self) -> None:
        """Mark sandbox as healthy and running."""
        self.status = ProjectSandboxStatus.RUNNING
        self.health_checked_at = datetime.utcnow()
        self.error_message = None

    def mark_unhealthy(self, reason: Optional[str] = None) -> None:
        """Mark sandbox as unhealthy (deprecated: use mark_error)."""
        self.mark_error(reason or "Unhealthy")

    def mark_error(self, error: str) -> None:
        """Mark sandbox as having an error."""
        self.status = ProjectSandboxStatus.ERROR
        self.error_message = error

    def mark_stopped(self) -> None:
        """Mark sandbox as stopped (deprecated: use mark_terminated)."""
        self.mark_terminated()

    def mark_terminated(self) -> None:
        """Mark sandbox as terminated."""
        self.status = ProjectSandboxStatus.TERMINATED

    def mark_connecting(self) -> None:
        """Mark sandbox as connecting (deprecated: use STARTING)."""
        self.status = ProjectSandboxStatus.STARTING

    def mark_disconnected(self) -> None:
        """Mark sandbox as disconnected (deprecated: use mark_error)."""
        self.mark_error("Disconnected")

    def mark_orphan(self) -> None:
        """Mark sandbox as orphan (deprecated: use ERROR with metadata)."""
        self.status = ProjectSandboxStatus.ERROR
        # Store orphan flag in metadata for tracking
        self.metadata["orphan"] = True

    def mark_creating(self) -> None:
        """Mark sandbox as being created (deprecated: use STARTING)."""
        self.status = ProjectSandboxStatus.STARTING

    def is_orphan(self) -> bool:
        """Check if this sandbox is an orphan.

        Deprecated: ORPHAN status is now tracked via metadata flag.
        """
        return self.metadata.get("orphan", False)

    def can_adopt(self) -> bool:
        """Check if this orphan sandbox can be adopted.

        Deprecated: Use metadata flag instead.
        """
        return self.is_orphan()

    def is_local(self) -> bool:
        """Check if this is a local sandbox."""
        return self.sandbox_type == SandboxType.LOCAL

    def is_cloud(self) -> bool:
        """Check if this is a cloud sandbox."""
        return self.sandbox_type == SandboxType.CLOUD

    def is_active(self) -> bool:
        """Check if sandbox is in an active state (running or starting)."""
        return self.status in (
            ProjectSandboxStatus.RUNNING,
            ProjectSandboxStatus.STARTING,
            # Legacy states for backward compatibility
            ProjectSandboxStatus.CREATING,
            ProjectSandboxStatus.CONNECTING,
        )

    def is_usable(self) -> bool:
        """Check if sandbox can be used for operations."""
        return self.status == ProjectSandboxStatus.RUNNING

    def needs_health_check(self, max_age_seconds: int = 60) -> bool:
        """Check if health check is needed based on last check time."""
        if self.health_checked_at is None:
            return True
        elapsed = (datetime.utcnow() - self.health_checked_at).total_seconds()
        return elapsed > max_age_seconds

    def get_connection_url(self) -> Optional[str]:
        """Get the connection URL for this sandbox."""
        if self.is_local() and self.local_config:
            return self.local_config.get_websocket_url()
        # For cloud sandboxes, URL is constructed from sandbox_id
        return None

    def update_local_config(self, config: LocalSandboxConfig) -> None:
        """Update local sandbox configuration."""
        if self.sandbox_type != SandboxType.LOCAL:
            raise ValueError("Cannot set local_config on cloud sandbox")
        self.local_config = config
        # Store in metadata for persistence
        self.metadata["local_config"] = config.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        result = {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "sandbox_id": self.sandbox_id,
            "sandbox_type": self.sandbox_type.value,
            "status": self.status.value,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "last_accessed_at": self.last_accessed_at.isoformat()
            if self.last_accessed_at
            else None,
            "health_checked_at": self.health_checked_at.isoformat()
            if self.health_checked_at
            else None,
            "error_message": self.error_message,
            "metadata": self.metadata,
            "local_config": self.local_config.to_dict() if self.local_config else None,
        }
        return result
