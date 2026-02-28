"""
Agent skill system components.

Provides type definitions for skill matching and prompt injection,
plus the SkillResourceLoader for syncing skill resources and
FileSystemSkillLoader for loading skills from SKILL.md files.
"""

from src.infrastructure.agent.skill.filesystem_loader import (
    FileSystemSkillLoader,
    LoadedSkill,
    SkillLoadResult,
)
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
    "FileSystemSkillLoader",
    "LoadedSkill",
    "SkillExecutionConfig",
    "SkillExecutionMode",
    "SkillLoadResult",
    "SkillMatchResult",
    "SkillProtocol",
    # Resources
    "SkillResourceLoader",
]
