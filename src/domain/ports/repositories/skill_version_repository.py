"""
SkillVersionRepository port for skill version persistence.

Repository interface for persisting and retrieving skill version snapshots.
"""

from abc import ABC, abstractmethod

from src.domain.model.agent.skill.skill_version import SkillVersion


class SkillVersionRepositoryPort(ABC):
    """Repository port for skill version persistence."""

    @abstractmethod
    async def create(self, version: SkillVersion) -> SkillVersion:
        """Create a new skill version snapshot."""
        pass

    @abstractmethod
    async def get_by_version(self, skill_id: str, version_number: int) -> SkillVersion | None:
        """Get a specific version of a skill."""
        pass

    @abstractmethod
    async def list_by_skill(
        self, skill_id: str, limit: int = 50, offset: int = 0
    ) -> list[SkillVersion]:
        """List all versions of a skill, ordered by version_number DESC."""
        pass

    @abstractmethod
    async def get_latest(self, skill_id: str) -> SkillVersion | None:
        """Get the latest version of a skill."""
        pass

    @abstractmethod
    async def get_max_version_number(self, skill_id: str) -> int:
        """Get the highest version_number for a skill. Returns 0 if none."""
        pass

    @abstractmethod
    async def count_by_skill(self, skill_id: str) -> int:
        """Count versions for a skill."""
        pass
