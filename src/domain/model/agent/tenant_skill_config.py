"""
TenantSkillConfig entity for controlling system skills at tenant level.

Allows tenants to disable or override system skills without affecting other tenants.
This enables multi-tenant isolation while preserving system skill defaults.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class TenantSkillAction(str, Enum):
    """
    Action to take on a system skill at tenant level.

    - DISABLE: Do not load this system skill for this tenant
    - OVERRIDE: Replace system skill with a tenant-level skill
    """

    DISABLE = "disable"
    OVERRIDE = "override"


@dataclass
class TenantSkillConfig:
    """
    Tenant-level configuration for system skills.

    Allows tenants to disable or override system skills without
    affecting other tenants.

    Attributes:
        id: Unique identifier for this config
        tenant_id: ID of the tenant
        system_skill_name: Name of the system skill to configure
        action: Action to take (disable or override)
        override_skill_id: ID of the tenant skill to use as override (when action=override)
        created_at: When this config was created
        updated_at: When this config was last modified
    """

    id: str
    tenant_id: str
    system_skill_name: str
    action: TenantSkillAction
    override_skill_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def __post_init__(self):
        """Validate the config."""
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.system_skill_name:
            raise ValueError("system_skill_name cannot be empty")
        if self.action == TenantSkillAction.OVERRIDE and not self.override_skill_id:
            raise ValueError("override_skill_id is required when action is override")

    def is_disabled(self) -> bool:
        """Check if this config disables the system skill."""
        return self.action == TenantSkillAction.DISABLE

    def is_override(self) -> bool:
        """Check if this config overrides the system skill."""
        return self.action == TenantSkillAction.OVERRIDE

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "system_skill_name": self.system_skill_name,
            "action": self.action.value,
            "override_skill_id": self.override_skill_id,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TenantSkillConfig":
        """Create from dictionary (e.g., from database)."""
        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            system_skill_name=data["system_skill_name"],
            action=TenantSkillAction(data["action"]),
            override_skill_id=data.get("override_skill_id"),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(timezone.utc),
        )

    @classmethod
    def create_disable(
        cls,
        tenant_id: str,
        system_skill_name: str,
    ) -> "TenantSkillConfig":
        """
        Create a config to disable a system skill.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill to disable

        Returns:
            New TenantSkillConfig instance
        """
        import uuid

        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            system_skill_name=system_skill_name,
            action=TenantSkillAction.DISABLE,
        )

    @classmethod
    def create_override(
        cls,
        tenant_id: str,
        system_skill_name: str,
        override_skill_id: str,
    ) -> "TenantSkillConfig":
        """
        Create a config to override a system skill.

        Args:
            tenant_id: Tenant ID
            system_skill_name: Name of the system skill to override
            override_skill_id: ID of the tenant skill to use instead

        Returns:
            New TenantSkillConfig instance
        """
        import uuid

        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            system_skill_name=system_skill_name,
            action=TenantSkillAction.OVERRIDE,
            override_skill_id=override_skill_id,
        )
