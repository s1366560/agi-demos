"""Skill entity for the Agent Skill System.

Represents a declarative skill that encapsulates domain knowledge and
tool compositions for specific task patterns.

Skills are the L2 layer in the four-layer capability architecture:
Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)

Three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants (read-only)
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills

Activation model (post 2026 refactor):
- Forced activation via slash command (``/skill-name``) — agent loads
  ``full_content`` as a mandatory system prompt and restricts the tool
  set to ``tools``.
- Advisory activation via the ``skill_loader`` tool — LLM voluntarily
  fetches ``full_content`` as a tool result.

There is no implicit trigger-pattern matching. The legacy fields
``trigger_type``, ``trigger_patterns``, ``prompt_template``,
``success_count`` and ``failure_count`` have been removed.
"""

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import TYPE_CHECKING, Any

from src.domain.model.agent.skill.skill_source import SkillSource

if TYPE_CHECKING:
    from src.domain.model.agent.skill.skill_permission import (
        SkillPermissionAction,
        SkillPermissionRule,
    )


class SkillStatus(str, Enum):
    """Status of a skill."""

    ACTIVE = "active"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


class SkillScope(str, Enum):
    """Scope of a skill for multi-tenant isolation.

    - SYSTEM: Built-in skills shared by all tenants (read-only)
    - TENANT: Tenant-level skills shared within a tenant
    - PROJECT: Project-specific skills
    """

    SYSTEM = "system"
    TENANT = "tenant"
    PROJECT = "project"


@dataclass
class Skill:
    """A skill that encapsulates domain knowledge and tool compositions."""

    id: str
    tenant_id: str
    name: str
    description: str
    tools: list[str]
    project_id: str | None = None
    status: SkillStatus = SkillStatus.ACTIVE
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] | None = None
    # Progressive loading
    source: SkillSource = SkillSource.DATABASE
    file_path: str | None = None
    full_content: str | None = None
    # Agent mode support — specify which agent modes can use this skill.
    # ["*"] means all modes, ["default", "plan"] means only those modes.
    agent_modes: list[str] = field(default_factory=lambda: ["*"])
    # Three-level scoping
    scope: SkillScope = SkillScope.TENANT
    is_system_skill: bool = False
    # AgentSkills.io spec fields
    license: str | None = None
    compatibility: str | None = None
    allowed_tools_raw: str | None = None
    allowed_tools_parsed: list[Any] = field(default_factory=list)
    spec_version: str = "1.0"
    # Version tracking
    current_version: int = 0
    version_label: str | None = None

    _NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    _NAME_MAX_LENGTH = 64
    _DESCRIPTION_MAX_LENGTH = 1024
    _COMPATIBILITY_MAX_LENGTH = 500

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("id cannot be empty")
        if not self.tenant_id:
            raise ValueError("tenant_id cannot be empty")
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.description:
            raise ValueError("description cannot be empty")
        if not self.tools:
            raise ValueError("tools cannot be empty")
        self._validate_agentskills_spec()

    def _validate_agentskills_spec(self) -> None:
        if len(self.name) > self._NAME_MAX_LENGTH:
            raise ValueError(
                f"Skill name must be 1-{self._NAME_MAX_LENGTH} characters, got {len(self.name)}"
            )
        if not self._NAME_PATTERN.match(self.name):
            raise ValueError(
                f"Skill name '{self.name}' must be lowercase with hyphens only, "
                "no leading/trailing/consecutive hyphens"
            )
        if len(self.description) > self._DESCRIPTION_MAX_LENGTH:
            raise ValueError(
                f"Description must be 1-{self._DESCRIPTION_MAX_LENGTH} characters, "
                f"got {len(self.description)}"
            )
        if self.compatibility and len(self.compatibility) > self._COMPATIBILITY_MAX_LENGTH:
            raise ValueError(
                f"Compatibility must be <={self._COMPATIBILITY_MAX_LENGTH} characters, "
                f"got {len(self.compatibility)}"
            )

    def is_active(self) -> bool:
        return self.status == SkillStatus.ACTIVE

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        if "*" in self.agent_modes:
            return True
        return agent_mode in self.agent_modes

    def check_permission(
        self,
        rules: list["SkillPermissionRule"],
    ) -> "SkillPermissionAction":
        from src.domain.model.agent.skill.skill_permission import evaluate_skill_permission

        return evaluate_skill_permission(self.name, rules)

    @property
    def agent_modes_set(self) -> set[str]:
        return set(self.agent_modes)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "source": self.source.value if self.source else None,
            "file_path": self.file_path,
            "agent_modes": list(self.agent_modes),
            "scope": self.scope.value,
            "is_system_skill": self.is_system_skill,
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools_raw": self.allowed_tools_raw,
            "allowed_tools_parsed": [
                t.to_dict() if hasattr(t, "to_dict") else t for t in self.allowed_tools_parsed
            ],
            "spec_version": self.spec_version,
            "current_version": self.current_version,
            "version_label": self.version_label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Skill":
        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            project_id=data.get("project_id"),
            name=data["name"],
            description=data["description"],
            tools=data.get("tools", []),
            status=SkillStatus(data.get("status", "active")),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(UTC),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(UTC),
            metadata=data.get("metadata"),
            agent_modes=data.get("agent_modes", ["*"]),
            scope=SkillScope(data.get("scope", "tenant")),
            is_system_skill=data.get("is_system_skill", False),
            license=data.get("license"),
            compatibility=data.get("compatibility"),
            allowed_tools_raw=data.get("allowed_tools_raw"),
            allowed_tools_parsed=data.get("allowed_tools_parsed", []),
            spec_version=data.get("spec_version", "1.0"),
            current_version=data.get("current_version", 0),
            version_label=data.get("version_label"),
        )

    @classmethod
    def create(  # noqa: PLR0913
        cls,
        tenant_id: str,
        name: str,
        description: str,
        tools: list[str],
        project_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        agent_modes: list[str] | None = None,
        scope: SkillScope = SkillScope.TENANT,
        is_system_skill: bool = False,
        full_content: str | None = None,
        license: str | None = None,
        compatibility: str | None = None,
        allowed_tools_raw: str | None = None,
        allowed_tools_parsed: list[Any] | None = None,
    ) -> "Skill":
        """Factory: build a new Skill with a generated UUID."""
        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            tools=tools,
            metadata=metadata,
            agent_modes=agent_modes or ["*"],
            scope=scope,
            is_system_skill=is_system_skill,
            full_content=full_content,
            license=license,
            compatibility=compatibility,
            allowed_tools_raw=allowed_tools_raw,
            allowed_tools_parsed=allowed_tools_parsed or [],
        )
