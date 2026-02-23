"""Skill registry for memstack-agent.

Provides a registry for managing and discovering skills:
- Register skills by definition or instance
- Match queries against registered skills
- Support for skill priority and filtering
- Thread-safe skill storage
"""

import logging
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional

from memstack_agent.skill.types import (
    Skill,
    SkillDefinition,
    SkillExecutionMode,
    SkillMatch,
    SkillMetadata,
    SkillStep,
    SkillTrigger,
    TriggerType,
)

logger = logging.getLogger(__name__)


@dataclass
class SkillRegistryConfig:
    """Configuration for skill registry.

    Attributes:
        match_threshold: Minimum score for skill match (default: 0.7)
        direct_execute_threshold: Score for direct execution (default: 0.95)
        max_matches: Maximum matches to return (default: 3)
        enable_semantic: Enable semantic matching (default: False)
    """

    match_threshold: float = 0.7
    direct_execute_threshold: float = 0.95
    max_matches: int = 3
    enable_semantic: bool = False


class SkillRegistry:
    """Thread-safe registry for managing skills.

    Provides:
    - Skill registration and deregistration
    - Query matching against skills
    - Skill lookup by ID or name
    - Priority-based skill ordering

    Example:
        registry = SkillRegistry()

        # Register a skill
        skill = SkillDefinition(
            id="web_search",
            name="Web Search",
            description="Search the web for information",
            tools=["search_web", "scrape_url"],
            trigger=SkillTrigger(
                type=TriggerType.KEYWORD,
                patterns=["search", "find", "look up"],
            ),
        )
        registry.register(skill)

        # Match a query
        matches = registry.match("search for Python tutorials")
        # Returns: [SkillMatch(skill=skill, score=1.0, mode=INJECT)]
    """

    def __init__(self, config: Optional[SkillRegistryConfig] = None) -> None:
        """Initialize skill registry.

        Args:
            config: Registry configuration
        """
        self._config = config or SkillRegistryConfig()
        self._skills: Dict[str, SkillDefinition] = {}
        self._instances: Dict[str, Skill] = {}
        self._lock = Lock()

    @property
    def count(self) -> int:
        """Number of registered skills."""
        return len(self._skills)

    def register(self, skill: SkillDefinition) -> None:
        """Register a skill definition.

        Args:
            skill: Skill definition to register

        Raises:
            ValueError: If skill with same ID already exists
        """
        with self._lock:
            if skill.id in self._skills:
                logger.warning(f"Overwriting existing skill: {skill.id}")
            self._skills[skill.id] = skill
            logger.debug(f"Registered skill: {skill.name} ({skill.id})")

    def register_instance(self, skill: Skill) -> None:
        """Register a skill instance (implements Skill protocol).

        Args:
            skill: Skill instance to register
        """
        with self._lock:
            self._instances[skill.id] = skill
            logger.debug(f"Registered skill instance: {skill.name} ({skill.id})")

    def unregister(self, skill_id: str) -> bool:
        """Unregister a skill by ID.

        Args:
            skill_id: ID of skill to remove

        Returns:
            True if skill was removed, False if not found
        """
        with self._lock:
            removed = False
            if skill_id in self._skills:
                del self._skills[skill_id]
                removed = True
            if skill_id in self._instances:
                del self._instances[skill_id]
                removed = True
            return removed

    def get(self, skill_id: str) -> Optional[SkillDefinition]:
        """Get a skill by ID.

        Args:
            skill_id: Skill ID to look up

        Returns:
            Skill definition or None if not found
        """
        return self._skills.get(skill_id)

    def get_instance(self, skill_id: str) -> Optional[Skill]:
        """Get a skill instance by ID.

        Args:
            skill_id: Skill ID to look up

        Returns:
            Skill instance or None if not found
        """
        return self._instances.get(skill_id)

    def get_by_name(self, name: str) -> Optional[SkillDefinition]:
        """Get a skill by name (case-insensitive).

        Args:
            name: Skill name to look up

        Returns:
            Skill definition or None if not found
        """
        name_lower = name.lower()
        for skill in self._skills.values():
            if skill.name.lower() == name_lower:
                return skill
        return None

    def list_all(self, include_disabled: bool = False) -> List[SkillDefinition]:
        """List all registered skills.

        Args:
            include_disabled: Include non-active skills

        Returns:
            List of skill definitions
        """
        skills = list(self._skills.values())
        if not include_disabled:
            skills = [s for s in skills if s.is_active()]
        return sorted(skills, key=lambda s: s.metadata.priority, reverse=True)

    def match(self, query: str) -> List[SkillMatch]:
        """Match a query against registered skills.

        Args:
            query: User query to match

        Returns:
            List of skill matches, sorted by score (highest first)
        """
        matches: List[SkillMatch] = []

        for skill in self._skills.values():
            # Skip inactive skills
            if not skill.is_active():
                continue

            # Calculate match score
            score = skill.matches_query(query)

            # Also check instance if available
            instance = self._instances.get(skill.id)
            if instance:
                instance_score = instance.matches_query(query)
                score = max(score, instance_score)

            # Check threshold
            if score >= self._config.match_threshold:
                mode = self._determine_mode(skill, score)
                matches.append(
                    SkillMatch(
                        skill=skill,
                        score=score,
                        mode=mode,
                    )
                )

        # Sort by score (descending) then priority (descending)
        matches.sort(key=lambda m: (m.score, m.skill.metadata.priority), reverse=True)

        # Limit results
        return matches[: self._config.max_matches]

    def match_best(self, query: str) -> Optional[SkillMatch]:
        """Get the best matching skill for a query.

        Args:
            query: User query to match

        Returns:
            Best skill match or None if no match
        """
        matches = self.match(query)
        return matches[0] if matches else None

    def _determine_mode(
        self,
        skill: SkillDefinition,
        score: float,
    ) -> SkillExecutionMode:
        """Determine execution mode based on skill and score.

        Args:
            skill: Matched skill
            score: Match score

        Returns:
            Recommended execution mode
        """
        # Check if skill specifies execution mode
        if skill.execution_mode == SkillExecutionMode.DIRECT:
            if score >= self._config.direct_execute_threshold:
                return SkillExecutionMode.DIRECT
            return SkillExecutionMode.INJECT

        # Default to skill's preferred mode
        return skill.execution_mode

    def filter_by_tags(self, tags: List[str]) -> List[SkillDefinition]:
        """Filter skills by tags.

        Args:
            tags: Tags to filter by

        Returns:
            Skills matching any of the tags
        """
        return [
            skill
            for skill in self._skills.values()
            if any(tag in skill.metadata.tags for tag in tags)
        ]

    def filter_by_tools(self, tools: List[str]) -> List[SkillDefinition]:
        """Filter skills by required tools.

        Args:
            tools: Tools that must be available

        Returns:
            Skills that use only the specified tools
        """
        tool_set = set(tools)
        return [
            skill
            for skill in self._skills.values()
            if set(skill.tools).issubset(tool_set)
        ]

    def clear(self) -> None:
        """Remove all registered skills."""
        with self._lock:
            self._skills.clear()
            self._instances.clear()


# Global registry instance
_global_registry: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    """Get the global skill registry.

    Creates a new registry if not initialized.

    Returns:
        Global SkillRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = SkillRegistry()
    return _global_registry


def create_skill(
    id: str,
    name: str,
    description: str,
    tools: List[str],
    trigger_patterns: Optional[List[str]] = None,
    trigger_type: TriggerType = TriggerType.KEYWORD,
    steps: Optional[List[Dict[str, Any]]] = None,
    **kwargs: Any,
) -> SkillDefinition:
    """Factory function to create a skill definition.

    Args:
        id: Unique skill ID
        name: Human-readable name
        description: Detailed description
        tools: List of tool names
        trigger_patterns: Patterns for skill activation
        trigger_type: Type of trigger matching
        steps: Execution steps (as dicts)
        **kwargs: Additional metadata

    Returns:
        SkillDefinition instance

    Example:
        skill = create_skill(
            id="code_review",
            name="Code Review",
            description="Review code for quality and security",
            tools=["read_file", "analyze_code", "write_comment"],
            trigger_patterns=["review", "check code", "analyze"],
            tags=["code", "quality"],
        )
    """
    # Build trigger
    trigger = None
    if trigger_patterns:
        trigger = SkillTrigger(
            type=trigger_type,
            patterns=trigger_patterns,
        )

    # Build steps
    skill_steps = []
    if steps:
        for step_dict in steps:
            skill_steps.append(
                SkillStep(
                    tool_name=step_dict.get("tool_name", ""),
                    description=step_dict.get("description", ""),
                    parameters=step_dict.get("parameters", {}),
                )
            )

    # Build metadata
    metadata = SkillMetadata(
        author=kwargs.get("author", ""),
        version=kwargs.get("version", "1.0.0"),
        tags=kwargs.get("tags", []),
        category=kwargs.get("category", "general"),
        priority=kwargs.get("priority", 0),
        timeout_seconds=kwargs.get("timeout_seconds", 300),
    )

    return SkillDefinition(
        id=id,
        name=name,
        description=description,
        tools=tools,
        steps=skill_steps,
        trigger=trigger,
        metadata=metadata,
        prompt_template=kwargs.get("prompt_template"),
        execution_mode=kwargs.get("execution_mode", SkillExecutionMode.INJECT),
    )


__all__ = [
    "SkillRegistryConfig",
    "SkillRegistry",
    "get_skill_registry",
    "create_skill",
]
