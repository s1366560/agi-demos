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
    """Status of a project-sandbox association."""

    PENDING = "pending"  # Sandbox creation requested but not yet ready
    CREATING = "creating"  # Sandbox is being created
    RUNNING = "running"  # Sandbox is running and healthy
    UNHEALTHY = "unhealthy"  # Sandbox is running but unhealthy
    STOPPED = "stopped"  # Sandbox is stopped but can be restarted
    TERMINATED = "terminated"  # Sandbox has been terminated
    ERROR = "error"  # Sandbox creation or operation failed
    CONNECTING = "connecting"  # Local sandbox connection in progress
    DISCONNECTED = "disconnected"  # Local sandbox disconnected
    ORPHAN = "orphan"  # Container exists but no valid association (discovered on startup)


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
    status: ProjectSandboxStatus = ProjectSandboxStatus.PENDING
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

    def _safe_transition(self, new_status: ProjectSandboxStatus) -> None:
        """Perform a safe state transition with validation.

        Uses the state machine to validate the transition is allowed.
        Logs warnings for invalid transitions but allows them for backwards compatibility.

        Args:
            new_status: The target status to transition to
        """
        from src.domain.model.sandbox.state_machine import get_state_machine

        state_machine = get_state_machine()
        if not state_machine.can_transition(self.status, new_status):
            # Log warning but allow transition for backwards compatibility
            import logging

            logger = logging.getLogger(__name__)
            logger.warning(
                f"Invalid state transition from {self.status.value} to {new_status.value} "
                f"for sandbox {self.sandbox_id}. Allowing for backwards compatibility."
            )
        self.status = new_status

    def mark_healthy(self) -> None:
        """Mark sandbox as healthy and running."""
        self._safe_transition(ProjectSandboxStatus.RUNNING)
        self.health_checked_at = datetime.utcnow()
        self.error_message = None

    def mark_unhealthy(self, reason: Optional[str] = None) -> None:
        """Mark sandbox as unhealthy."""
        self._safe_transition(ProjectSandboxStatus.UNHEALTHY)
        self.health_checked_at = datetime.utcnow()
        if reason:
            self.error_message = reason

    def mark_error(self, error: str) -> None:
        """Mark sandbox as having an error."""
        self._safe_transition(ProjectSandboxStatus.ERROR)
        self.error_message = error

    def mark_stopped(self) -> None:
        """Mark sandbox as stopped."""
        self._safe_transition(ProjectSandboxStatus.STOPPED)

    def mark_terminated(self) -> None:
        """Mark sandbox as terminated."""
        self._safe_transition(ProjectSandboxStatus.TERMINATED)

    def mark_connecting(self) -> None:
        """Mark local sandbox as connecting."""
        self._safe_transition(ProjectSandboxStatus.CONNECTING)

    def mark_disconnected(self) -> None:
        """Mark local sandbox as disconnected."""
        self._safe_transition(ProjectSandboxStatus.DISCONNECTED)

    def mark_orphan(self) -> None:
        """Mark sandbox as orphan (discovered container without valid association)."""
        self.status = ProjectSandboxStatus.ORPHAN

    def mark_creating(self) -> None:
        """Mark sandbox as being created."""
        self._safe_transition(ProjectSandboxStatus.CREATING)

    def is_orphan(self) -> bool:
        """Check if this sandbox is an orphan."""
        return self.status == ProjectSandboxStatus.ORPHAN

    def can_adopt(self) -> bool:
        """Check if this orphan sandbox can be adopted.

        Returns:
            True if the sandbox is an orphan and can be adopted
        """
        return self.status == ProjectSandboxStatus.ORPHAN

    def is_local(self) -> bool:
        """Check if this is a local sandbox."""
        return self.sandbox_type == SandboxType.LOCAL

    def is_cloud(self) -> bool:
        """Check if this is a cloud sandbox."""
        return self.sandbox_type == SandboxType.CLOUD

    def is_active(self) -> bool:
        """Check if sandbox is in an active state (running or creating)."""
        return self.status in (
            ProjectSandboxStatus.RUNNING,
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
