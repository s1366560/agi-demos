"""
Skill entity for the Agent Skill System.

Represents a declarative skill that encapsulates domain knowledge and
tool compositions for specific task patterns.

Skills are the L2 layer in the four-layer capability architecture:
Tool (L1) -> Skill (L2) -> SubAgent (L3) -> Agent (L4)

Three-level scoping for multi-tenant isolation:
- system: Built-in skills shared by all tenants (read-only)
- tenant: Tenant-level skills shared within a tenant
- project: Project-specific skills

Attributes:
    trigger_type: How the skill is activated (keyword, semantic, hybrid)
    trigger_patterns: Patterns that activate this skill
    tools: List of tools this skill can use
    prompt_template: Optional template for skill execution
    source: Where the skill is loaded from (filesystem, database, hybrid)
    file_path: Path to SKILL.md file (if from filesystem)
    full_content: Full markdown content (Tier 3 content)
    scope: Skill scope (system, tenant, project)
    is_system_skill: Whether this is a system built-in skill
"""

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Set

from src.domain.model.agent.skill_source import SkillSource

if TYPE_CHECKING:
    from src.domain.model.agent.skill_permission import SkillPermissionAction, SkillPermissionRule


class TriggerType(str, Enum):
    """Type of trigger for skill activation."""

    KEYWORD = "keyword"
    SEMANTIC = "semantic"
    HYBRID = "hybrid"


class SkillStatus(str, Enum):
    """Status of a skill."""

    ACTIVE = "active"
    DISABLED = "disabled"
    DEPRECATED = "deprecated"


class SkillScope(str, Enum):
    """
    Scope of a skill for multi-tenant isolation.

    - SYSTEM: Built-in skills shared by all tenants (read-only)
    - TENANT: Tenant-level skills shared within a tenant
    - PROJECT: Project-specific skills
    """

    SYSTEM = "system"
    TENANT = "tenant"
    PROJECT = "project"


@dataclass(frozen=True)
class TriggerPattern:
    """
    A pattern that can activate a skill.

    Attributes:
        pattern: The trigger pattern (keyword or semantic description)
        weight: Importance weight for this pattern (0-1)
        examples: Example queries that match this pattern
    """

    pattern: str
    weight: float = 1.0
    examples: List[str] = field(default_factory=list)

    def __post_init__(self):
        """Validate the trigger pattern."""
        if not self.pattern:
            raise ValueError("pattern cannot be empty")
        if not 0 <= self.weight <= 1:
            raise ValueError("weight must be between 0 and 1")

    def matches_keyword(self, query: str) -> bool:
        """Check if query contains the keyword pattern."""
        return self.pattern.lower() in query.lower()

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "pattern": self.pattern,
            "weight": self.weight,
            "examples": list(self.examples) if self.examples else [],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TriggerPattern":
        """Create from dictionary."""
        return cls(
            pattern=data["pattern"],
            weight=data.get("weight", 1.0),
            examples=data.get("examples", []),
        )


@dataclass
class Skill:
    """
    A skill that encapsulates domain knowledge and tool compositions.

    Skills represent declarative knowledge that can be triggered by
    specific patterns and executed using a defined set of tools.

    Three-level scoping for multi-tenant isolation:
    - SYSTEM: Built-in skills shared by all tenants (read-only)
    - TENANT: Tenant-level skills shared within a tenant
    - PROJECT: Project-specific skills

    Attributes:
        id: Unique identifier for this skill
        tenant_id: ID of the tenant that owns this skill
        project_id: Optional project-specific skill
        name: Human-readable name
        description: What this skill does
        trigger_type: How the skill is activated
        trigger_patterns: Patterns that activate this skill
        tools: List of tool names this skill can use
        prompt_template: Optional template for skill execution
        status: Current status of the skill
        success_count: Number of successful executions
        failure_count: Number of failed executions
        created_at: When this skill was created
        updated_at: When this skill was last modified
        metadata: Optional additional metadata
        scope: Skill scope (system, tenant, project)
        is_system_skill: Whether this is a system built-in skill
    """

    id: str
    tenant_id: str
    name: str
    description: str
    trigger_type: TriggerType
    trigger_patterns: List[TriggerPattern]
    tools: List[str]
    project_id: Optional[str] = None
    prompt_template: Optional[str] = None
    status: SkillStatus = SkillStatus.ACTIVE
    success_count: int = 0
    failure_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Optional[Dict[str, Any]] = None
    # New fields for progressive loading
    source: SkillSource = SkillSource.DATABASE
    file_path: Optional[str] = None
    full_content: Optional[str] = None
    # Agent mode support - specify which agent modes can use this skill
    # ["*"] means all modes, ["default", "plan"] means only these modes
    agent_modes: List[str] = field(default_factory=lambda: ["*"])
    # New fields for three-level scoping
    scope: SkillScope = SkillScope.TENANT
    is_system_skill: bool = False
    # AgentSkills.io spec fields
    license: Optional[str] = None  # License identifier (e.g., "MIT", "Apache-2.0")
    compatibility: Optional[str] = None  # Environment requirements (≤500 chars)
    allowed_tools_raw: Optional[str] = None  # Raw allowed-tools string
    allowed_tools_parsed: List[Any] = field(default_factory=list)  # List[AllowedTool]
    spec_version: str = "1.0"  # AgentSkills.io spec version

    # Name validation pattern (AgentSkills.io spec)
    _NAME_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    _NAME_MAX_LENGTH = 64
    _DESCRIPTION_MAX_LENGTH = 1024
    _COMPATIBILITY_MAX_LENGTH = 500

    def __post_init__(self):
        """Validate the skill."""
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
        if self.success_count < 0:
            raise ValueError("success_count must be non-negative")
        if self.failure_count < 0:
            raise ValueError("failure_count must be non-negative")
        # AgentSkills.io spec validation
        self._validate_agentskills_spec()

    def _validate_agentskills_spec(self) -> None:
        """
        Validate AgentSkills.io specification constraints.

        Raises:
            ValueError: If any spec constraint is violated
        """
        # Name: 1-64 chars, lowercase, hyphens only
        if len(self.name) > self._NAME_MAX_LENGTH:
            raise ValueError(
                f"Skill name must be 1-{self._NAME_MAX_LENGTH} characters, got {len(self.name)}"
            )
        if not self._NAME_PATTERN.match(self.name):
            raise ValueError(
                f"Skill name '{self.name}' must be lowercase with hyphens only, "
                f"no leading/trailing/consecutive hyphens"
            )

        # Description: 1-1024 chars
        if len(self.description) > self._DESCRIPTION_MAX_LENGTH:
            raise ValueError(
                f"Description must be 1-{self._DESCRIPTION_MAX_LENGTH} characters, "
                f"got {len(self.description)}"
            )

        # Compatibility: ≤500 chars
        if self.compatibility and len(self.compatibility) > self._COMPATIBILITY_MAX_LENGTH:
            raise ValueError(
                f"Compatibility must be <={self._COMPATIBILITY_MAX_LENGTH} characters, "
                f"got {len(self.compatibility)}"
            )

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        total = self.success_count + self.failure_count
        if total == 0:
            return 1.0
        return self.success_count / total

    @property
    def usage_count(self) -> int:
        """Total number of times this skill has been used."""
        return self.success_count + self.failure_count

    def is_active(self) -> bool:
        """Check if skill is active."""
        return self.status == SkillStatus.ACTIVE

    def is_accessible_by_agent(self, agent_mode: str) -> bool:
        """
        Check if this skill is accessible by the specified agent mode.

        Args:
            agent_mode: The agent mode to check (e.g., "default", "plan", "explore")

        Returns:
            True if the skill is accessible by the agent mode
        """
        if "*" in self.agent_modes:
            return True
        return agent_mode in self.agent_modes

    def check_permission(
        self,
        rules: List["SkillPermissionRule"],
    ) -> "SkillPermissionAction":
        """
        Check permission for this skill using a list of rules.

        Reference: OpenCode PermissionNext.evaluate()

        Uses last-match-wins strategy: the last matching rule determines
        the permission action.

        Args:
            rules: List of SkillPermissionRule objects

        Returns:
            SkillPermissionAction (ALLOW, DENY, or ASK)

        Example:
            from src.domain.model.agent.skill_permission import (
                SkillPermissionRule,
                SkillPermissionAction,
            )

            rules = [
                SkillPermissionRule("*", SkillPermissionAction.ASK),
                SkillPermissionRule("code-*", SkillPermissionAction.ALLOW),
            ]
            action = skill.check_permission(rules)
        """
        from src.domain.model.agent.skill_permission import evaluate_skill_permission

        return evaluate_skill_permission(self.name, rules)

    @property
    def agent_modes_set(self) -> Set[str]:
        """Return agent_modes as a set for fast lookup."""
        return set(self.agent_modes)

    def matches_query(self, query: str) -> float:
        """
        Calculate how well this skill matches a query.

        Returns a score between 0 and 1.
        """
        if not self.is_active():
            return 0.0

        if self.trigger_type == TriggerType.KEYWORD:
            return self._match_keywords(query)
        elif self.trigger_type == TriggerType.SEMANTIC:
            return self._match_semantic(query)
        else:  # HYBRID
            keyword_score = self._match_keywords(query)
            semantic_score = self._match_semantic(query)
            return max(keyword_score, semantic_score)

    def _match_keywords(self, query: str) -> float:
        """Match query against keyword patterns."""
        if not self.trigger_patterns:
            return 0.0

        max_score = 0.0
        for pattern in self.trigger_patterns:
            if pattern.matches_keyword(query):
                max_score = max(max_score, pattern.weight)

        return max_score

    def _match_semantic(self, query: str) -> float:
        """
        Match query semantically against patterns.

        This is a simple implementation using keyword overlap.
        Can be enhanced with embeddings for better semantic matching.
        """
        if not self.trigger_patterns:
            return 0.0

        query_lower = query.lower()
        query_words = set(query_lower.split())

        max_score = 0.0
        for pattern in self.trigger_patterns:
            pattern_words = set(pattern.pattern.lower().split())
            if pattern_words:
                overlap = len(query_words.intersection(pattern_words))
                score = (overlap / len(pattern_words)) * pattern.weight
                max_score = max(max_score, score)

        return min(max_score, 1.0)

    def record_usage(self, success: bool) -> "Skill":
        """
        Record a usage of this skill.

        Args:
            success: Whether the execution was successful

        Returns:
            Updated skill
        """
        return Skill(
            id=self.id,
            tenant_id=self.tenant_id,
            project_id=self.project_id,
            name=self.name,
            description=self.description,
            trigger_type=self.trigger_type,
            trigger_patterns=list(self.trigger_patterns),
            tools=list(self.tools),
            prompt_template=self.prompt_template,
            status=self.status,
            success_count=self.success_count + (1 if success else 0),
            failure_count=self.failure_count + (0 if success else 1),
            created_at=self.created_at,
            updated_at=datetime.now(timezone.utc),
            metadata=self.metadata,
            source=self.source,
            file_path=self.file_path,
            full_content=self.full_content,
            agent_modes=list(self.agent_modes),
            scope=self.scope,
            is_system_skill=self.is_system_skill,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API responses."""
        return {
            "id": self.id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "name": self.name,
            "description": self.description,
            "trigger_type": self.trigger_type.value,
            "trigger_patterns": [p.to_dict() for p in self.trigger_patterns],
            "tools": list(self.tools),
            "prompt_template": self.prompt_template,
            "status": self.status.value,
            "success_rate": self.success_rate,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "usage_count": self.usage_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "metadata": self.metadata,
            "source": self.source.value if self.source else None,
            "file_path": self.file_path,
            "agent_modes": list(self.agent_modes),
            "scope": self.scope.value,
            "is_system_skill": self.is_system_skill,
            # AgentSkills.io spec fields
            "license": self.license,
            "compatibility": self.compatibility,
            "allowed_tools_raw": self.allowed_tools_raw,
            "allowed_tools_parsed": [
                t.to_dict() if hasattr(t, "to_dict") else t for t in self.allowed_tools_parsed
            ],
            "spec_version": self.spec_version,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Skill":
        """Create from dictionary (e.g., from database)."""
        trigger_patterns = [TriggerPattern.from_dict(p) for p in data.get("trigger_patterns", [])]

        return cls(
            id=data["id"],
            tenant_id=data["tenant_id"],
            project_id=data.get("project_id"),
            name=data["name"],
            description=data["description"],
            trigger_type=TriggerType(data.get("trigger_type", "keyword")),
            trigger_patterns=trigger_patterns,
            tools=data.get("tools", []),
            prompt_template=data.get("prompt_template"),
            status=SkillStatus(data.get("status", "active")),
            success_count=data.get("success_count", 0),
            failure_count=data.get("failure_count", 0),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(timezone.utc),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(timezone.utc),
            metadata=data.get("metadata"),
            agent_modes=data.get("agent_modes", ["*"]),
            scope=SkillScope(data.get("scope", "tenant")),
            is_system_skill=data.get("is_system_skill", False),
            # AgentSkills.io spec fields
            license=data.get("license"),
            compatibility=data.get("compatibility"),
            allowed_tools_raw=data.get("allowed_tools_raw"),
            allowed_tools_parsed=data.get("allowed_tools_parsed", []),
            spec_version=data.get("spec_version", "1.0"),
        )

    @classmethod
    def create(
        cls,
        tenant_id: str,
        name: str,
        description: str,
        tools: List[str],
        trigger_type: TriggerType = TriggerType.KEYWORD,
        trigger_patterns: Optional[List[TriggerPattern]] = None,
        project_id: Optional[str] = None,
        prompt_template: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        agent_modes: Optional[List[str]] = None,
        scope: SkillScope = SkillScope.TENANT,
        is_system_skill: bool = False,
        full_content: Optional[str] = None,
        # AgentSkills.io spec fields
        license: Optional[str] = None,
        compatibility: Optional[str] = None,
        allowed_tools_raw: Optional[str] = None,
        allowed_tools_parsed: Optional[List[Any]] = None,
    ) -> "Skill":
        """
        Create a new skill.

        Args:
            tenant_id: Tenant ID
            name: Skill name
            description: What this skill does
            tools: List of tool names
            trigger_type: How the skill is activated
            trigger_patterns: Patterns that activate this skill
            project_id: Optional project ID
            prompt_template: Optional prompt template
            metadata: Optional metadata
            agent_modes: List of agent modes that can use this skill (default: ["*"])
            scope: Skill scope (system, tenant, project)
            is_system_skill: Whether this is a system built-in skill
            full_content: Full SKILL.md content
            license: License identifier (e.g., "MIT", "Apache-2.0")
            compatibility: Environment requirements
            allowed_tools_raw: Raw allowed-tools string
            allowed_tools_parsed: Parsed AllowedTool list

        Returns:
            New skill instance
        """
        import uuid

        return cls(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            project_id=project_id,
            name=name,
            description=description,
            trigger_type=trigger_type,
            trigger_patterns=trigger_patterns or [],
            tools=tools,
            prompt_template=prompt_template,
            metadata=metadata,
            agent_modes=agent_modes or ["*"],
            scope=scope,
            is_system_skill=is_system_skill,
            full_content=full_content,
            # AgentSkills.io spec fields
            license=license,
            compatibility=compatibility,
            allowed_tools_raw=allowed_tools_raw,
            allowed_tools_parsed=allowed_tools_parsed or [],
        )
