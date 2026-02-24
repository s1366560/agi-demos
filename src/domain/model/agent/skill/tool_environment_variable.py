"""Tool Environment Variable entity for agent tool configuration.

Environment variables are scoped to tools and can be stored at tenant
or project level for multi-tenant isolation.
"""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import Entity


class EnvVarScope(str, Enum):
    """Scope level for environment variables."""

    TENANT = "tenant"  # Tenant-level, shared across all projects
    PROJECT = "project"  # Project-specific, overrides tenant-level


@dataclass(kw_only=True)
class ToolEnvironmentVariable(Entity):
    """
    Environment variable for agent tools.

    Stores encrypted environment variables needed by tools,
    scoped by tenant and optionally by project.

    Attributes:
        tenant_id: Tenant that owns this variable
        project_id: Optional project for project-scoped variables
        tool_name: Name of the tool that uses this variable
        variable_name: Name of the environment variable
        encrypted_value: AES-256-GCM encrypted value
        description: Human-readable description
        is_required: Whether this variable is required for tool operation
        is_secret: Whether to mask this value in logs/outputs
        scope: Tenant or project level scope
        created_at: When the variable was created
        updated_at: When the variable was last updated
    """

    tenant_id: str
    tool_name: str
    variable_name: str
    encrypted_value: str
    project_id: str | None = None
    description: str | None = None
    is_required: bool = True
    is_secret: bool = True
    scope: EnvVarScope = EnvVarScope.TENANT
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    def __post_init__(self) -> None:
        """Validate the entity after initialization."""
        if not self.tenant_id:
            raise ValueError("tenant_id is required")
        if not self.tool_name:
            raise ValueError("tool_name is required")
        if not self.variable_name:
            raise ValueError("variable_name is required")
        if not self.encrypted_value:
            raise ValueError("encrypted_value is required")

        # If project_id is provided, scope must be PROJECT
        if self.project_id and self.scope != EnvVarScope.PROJECT:
            self.scope = EnvVarScope.PROJECT

    def update_value(self, new_encrypted_value: str) -> None:
        """Update the encrypted value."""
        self.encrypted_value = new_encrypted_value
        self.updated_at = datetime.now(UTC)

    def update_description(self, description: str) -> None:
        """Update the description."""
        self.description = description
        self.updated_at = datetime.now(UTC)

    @property
    def scoped_key(self) -> str:
        """Return a unique key for this variable within its scope."""
        if self.project_id:
            return f"{self.tenant_id}:{self.project_id}:{self.tool_name}:{self.variable_name}"
        return f"{self.tenant_id}::{self.tool_name}:{self.variable_name}"
