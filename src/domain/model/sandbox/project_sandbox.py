"""Project-Sandbox association domain model.

This module defines the domain model for managing the lifecycle association
between Projects and their dedicated Sandbox instances.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional

from src.domain.shared_kernel import Entity


class ProjectSandboxStatus(Enum):
    """Status of a project-sandbox association."""

    PENDING = "pending"  # Sandbox creation requested but not yet ready
    CREATING = "creating"  # Sandbox is being created
    RUNNING = "running"  # Sandbox is running and healthy
    UNHEALTHY = "unhealthy"  # Sandbox is running but unhealthy
    STOPPED = "stopped"  # Sandbox is stopped but can be restarted
    TERMINATED = "terminated"  # Sandbox has been terminated
    ERROR = "error"  # Sandbox creation or operation failed


@dataclass(kw_only=True)
class ProjectSandbox(Entity):
    """Project-Sandbox lifecycle association entity.

    Each project should have exactly one persistent sandbox that:
    - Is created on first use (lazy initialization)
    - Remains running until project deletion or manual termination
    - Can be auto-restarted if unhealthy
    - Provides isolated environment for project-specific operations

    Attributes:
        project_id: Associated project ID
        tenant_id: Tenant ID for scoping
        sandbox_id: Unique sandbox instance identifier
        status: Current lifecycle status
        created_at: When the association was created
        started_at: When the sandbox container was started
        last_accessed_at: Last time the sandbox was used
        health_checked_at: Last health check timestamp
        error_message: Error description if in ERROR status
        metadata: Additional configuration and state
    """

    project_id: str
    tenant_id: str
    sandbox_id: str
    status: ProjectSandboxStatus = ProjectSandboxStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    last_accessed_at: datetime = field(default_factory=datetime.utcnow)
    health_checked_at: Optional[datetime] = None
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def mark_accessed(self) -> None:
        """Update last accessed timestamp."""
        self.last_accessed_at = datetime.utcnow()

    def mark_healthy(self) -> None:
        """Mark sandbox as healthy and running."""
        self.status = ProjectSandboxStatus.RUNNING
        self.health_checked_at = datetime.utcnow()
        self.error_message = None

    def mark_unhealthy(self, reason: Optional[str] = None) -> None:
        """Mark sandbox as unhealthy."""
        self.status = ProjectSandboxStatus.UNHEALTHY
        self.health_checked_at = datetime.utcnow()
        if reason:
            self.error_message = reason

    def mark_error(self, error: str) -> None:
        """Mark sandbox as having an error."""
        self.status = ProjectSandboxStatus.ERROR
        self.error_message = error

    def mark_stopped(self) -> None:
        """Mark sandbox as stopped."""
        self.status = ProjectSandboxStatus.STOPPED

    def mark_terminated(self) -> None:
        """Mark sandbox as terminated."""
        self.status = ProjectSandboxStatus.TERMINATED

    def is_active(self) -> bool:
        """Check if sandbox is in an active state (running or creating)."""
        return self.status in (
            ProjectSandboxStatus.RUNNING,
            ProjectSandboxStatus.CREATING,
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

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "sandbox_id": self.sandbox_id,
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
        }
