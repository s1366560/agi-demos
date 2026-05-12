"""Agent skill system components.

Exposes the SkillProtocol consumed by the ReAct agent and the
SkillResourceLoader for syncing skill resources. Filesystem loading
lives in src.application.services.filesystem_skill_loader.
"""

from src.infrastructure.agent.skill.skill_resource_loader import (
    SkillResourceLoader,
)
from src.infrastructure.agent.skill.types import SkillProtocol

__all__ = [
    "SkillProtocol",
    "SkillResourceLoader",
]
