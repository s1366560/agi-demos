"""Skill type definitions for memstack-agent.

This module provides core types for skill system:
- Skill: Protocol interface for skill implementations
- SkillDefinition: Immutable skill definition
- SkillTrigger: Trigger patterns for skill activation
- SkillStatus: Skill lifecycle status
- SkillStep: Single step in skill execution

All types are immutable (frozen dataclass).
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Protocol, runtime_checkable


class SkillStatus(str, Enum):
    """Skill lifecycle status."""

    DRAFT = "draft"  # Under development
    ACTIVE = "active"  # Ready for use
    DEPRECATED = "deprecated"  # Marked for removal
    DISABLED = "disabled"  # Temporarily disabled


class TriggerType(str, Enum):
    """Types of skill triggers."""

    KEYWORD = "keyword"  # Exact keyword match
    SEMANTIC = "semantic"  # Semantic similarity
    REGEX = "regex"  # Regular expression pattern
    HYBRID = "hybrid"  # Combination of triggers


class SkillExecutionMode(str, Enum):
    """How a skill should be executed."""

    DIRECT = "direct"  # Execute directly without LLM
    INJECT = "inject"  # Inject skill context into LLM prompt
    ASSISTED = "assisted"  # LLM assists with tool selection


@dataclass(frozen=True, kw_only=True)
class SkillTrigger:
    """Immutable trigger pattern for skill activation.

    Skills can be triggered by:
    - Keywords: Exact keyword matching
    - Patterns: Regex patterns
    - Semantic: Vector similarity (requires embedding)

    Attributes:
        type: Trigger type
        patterns: List of patterns (keywords, regex, etc.)
        threshold: Match threshold (0.0 to 1.0)
        case_sensitive: Whether matching is case sensitive
    """

    type: TriggerType = TriggerType.KEYWORD
    patterns: list[str] = field(default_factory=list)
    threshold: float = 0.9
    case_sensitive: bool = False

    def matches(self, text: str) -> float:
        """Check if text matches this trigger.

        Args:
            text: Text to match against

        Returns:
            Match score (0.0 to 1.0)
        """
        if self.type == TriggerType.KEYWORD:
            return self._match_keywords(text)
        elif self.type == TriggerType.REGEX:
            return self._match_regex(text)
        else:
            # Semantic matching requires external embedding
            return 0.0

    def _match_keywords(self, text: str) -> float:
        """Match against keywords."""
        if not self.patterns:
            return 0.0

        check_text = text if self.case_sensitive else text.lower()
        matches = 0

        for pattern in self.patterns:
            check_pattern = pattern if self.case_sensitive else pattern.lower()
            if check_pattern in check_text:
                matches += 1

        return matches / len(self.patterns) if self.patterns else 0.0

    def _match_regex(self, text: str) -> float:
        """Match against regex patterns."""
        import re

        if not self.patterns:
            return 0.0

        flags = 0 if self.case_sensitive else re.IGNORECASE
        matches = 0

        for pattern in self.patterns:
            try:
                if re.search(pattern, text, flags):
                    matches += 1
            except re.error:
                continue

        return matches / len(self.patterns) if self.patterns else 0.0


@dataclass(frozen=True, kw_only=True)
class SkillStep:
    """Immutable single step in skill execution.

    A skill step represents a single tool invocation with
    optional preprocessing and postprocessing.

    Attributes:
        tool_name: Name of the tool to invoke
        description: Human-readable step description
        parameters: Static parameters for tool
        parameter_template: Jinja2 template for dynamic parameters
        condition: Optional condition for step execution
        on_error: Error handling strategy (skip, fail, retry)
        retry_count: Number of retries on failure
    """

    tool_name: str
    description: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    parameter_template: str | None = None  # Jinja2 template
    condition: str | None = None  # Expression for conditional execution
    on_error: str = "fail"  # skip, fail, retry
    retry_count: int = 0


@dataclass(frozen=True, kw_only=True)
class SkillMetadata:
    """Immutable skill metadata.

    Attributes:
        author: Skill author
        version: Skill version (semver)
        tags: Categorization tags
        category: Skill category
        priority: Execution priority (higher = more important)
        timeout_seconds: Maximum execution time
        requires_confirmation: Whether user confirmation is required
        visible_to_model: Whether skill is visible to LLM
    """

    author: str = ""
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    category: str = "general"
    priority: int = 0
    timeout_seconds: int = 300
    requires_confirmation: bool = False
    visible_to_model: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class SkillDefinition:
    """Immutable skill definition for LLM consumption.

    A Skill is a declarative composition of tools with:
    - Trigger patterns for automatic activation
    - Steps defining tool execution sequence
    - Optional prompt template for LLM assistance

    Skills enable reusable workflows that can be triggered
    automatically based on user queries.

    Attributes:
        id: Unique skill identifier
        name: Human-readable skill name
        description: Detailed skill description
        tools: List of tool names used by this skill
        steps: Ordered list of execution steps
        trigger: Trigger pattern for skill activation
        prompt_template: Optional Jinja2 template for LLM context
        status: Current skill status
        metadata: Additional skill metadata
        execution_mode: How the skill should be executed
    """

    id: str
    name: str
    description: str
    tools: list[str] = field(default_factory=list)
    steps: list[SkillStep] = field(default_factory=list)
    trigger: SkillTrigger | None = None
    prompt_template: str | None = None
    status: SkillStatus = SkillStatus.ACTIVE
    metadata: SkillMetadata = field(default_factory=SkillMetadata)
    execution_mode: SkillExecutionMode = SkillExecutionMode.INJECT

    def matches_query(self, query: str) -> float:
        """Calculate match score for a query.

        Args:
            query: User query to match

        Returns:
            Match score (0.0 to 1.0)
        """
        if not self.trigger:
            return 0.0

        return self.trigger.matches(query)

    def is_active(self) -> bool:
        """Check if skill is active and ready for use."""
        return self.status == SkillStatus.ACTIVE

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "tools": list(self.tools),
            "steps": [
                {
                    "tool_name": step.tool_name,
                    "description": step.description,
                    "parameters": step.parameters,
                }
                for step in self.steps
            ],
            "trigger": {
                "type": self.trigger.type.value if self.trigger else None,
                "patterns": list(self.trigger.patterns) if self.trigger else [],
                "threshold": self.trigger.threshold if self.trigger else 0.9,
            }
            if self.trigger
            else None,
            "status": self.status.value,
            "execution_mode": self.execution_mode.value,
            "metadata": {
                "author": self.metadata.author,
                "version": self.metadata.version,
                "tags": list(self.metadata.tags),
                "category": self.metadata.category,
            },
        }


@runtime_checkable
class Skill(Protocol):
    """Protocol for skill implementations.

    Any object implementing this interface can be used as a skill.
    Supports both declarative (SkillDefinition) and programmatic skills.

    Example:
        class MySkill:
            id = "my_skill"
            name = "My Skill"
            description = "Does something useful"

            def matches_query(self, query: str) -> float:
                return 0.95 if "my keyword" in query.lower() else 0.0

            async def execute(self, context: Dict[str, Any]) -> Any:
                # Implementation
                ...
    """

    @property
    def id(self) -> str:
        """Unique skill identifier."""
        ...

    @property
    def name(self) -> str:
        """Human-readable skill name."""
        ...

    @property
    def description(self) -> str:
        """Detailed skill description."""
        ...

    def matches_query(self, query: str) -> float:
        """Calculate match score for a query.

        Args:
            query: User query to match

        Returns:
            Match score (0.0 to 1.0)
        """
        ...

    async def execute(self, context: dict[str, Any], **kwargs: Any) -> Any:
        """Execute the skill.

        Args:
            context: Execution context
            **kwargs: Additional skill-specific arguments

        Returns:
            Execution result
        """
        ...


@dataclass(frozen=True, kw_only=True)
class SkillMatch:
    """Immutable result of skill matching.

    Attributes:
        skill: Matched skill (or None)
        score: Match score (0.0 to 1.0)
        mode: Recommended execution mode
    """

    skill: SkillDefinition | None = None
    score: float = 0.0
    mode: SkillExecutionMode = SkillExecutionMode.INJECT

    @property
    def matched(self) -> bool:
        """Check if a skill was matched."""
        return self.skill is not None and self.score > 0.0


@dataclass(frozen=True, kw_only=True)
class SkillExecutionResult:
    """Immutable result of skill execution.

    Attributes:
        skill_id: ID of executed skill
        success: Whether execution succeeded
        output: Skill output/result
        error: Error message if failed
        tool_results: Results from each tool step
        execution_time_ms: Total execution time
    """

    skill_id: str
    success: bool
    output: Any = None
    error: str | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    execution_time_ms: int = 0


__all__ = [
    "Skill",
    "SkillDefinition",
    "SkillExecutionMode",
    "SkillExecutionResult",
    "SkillMatch",
    "SkillMetadata",
    "SkillStatus",
    "SkillStep",
    "SkillTrigger",
    "TriggerType",
]
