"""
Agent skill system components.

Provides type definitions for skill matching and prompt injection,
plus the SkillResourceLoader for syncing skill resources.
"""

from src.infrastructure.agent.skill.orchestrator import (
    SkillExecutionConfig,
    SkillExecutionMode,
    SkillMatchResult,
    SkillProtocol,
)
from src.infrastructure.agent.skill.skill_resource_loader import (
    SkillResourceLoader,
)

__all__ = [
    "SkillExecutionConfig",
    "SkillExecutionMode",
    "SkillMatchResult",
    "SkillProtocol",
    # Resources
    "SkillResourceLoader",
]
