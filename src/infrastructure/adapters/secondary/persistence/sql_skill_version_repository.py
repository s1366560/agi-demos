"""
SQLAlchemy implementation of SkillVersionRepository.

Persists skill version snapshots including SKILL.md content and resource files.
"""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.skill.skill_version import SkillVersion
from src.domain.ports.repositories.skill_version_repository import SkillVersionRepositoryPort
from src.infrastructure.adapters.secondary.persistence.models import (
    SkillVersion as DBSkillVersion,
)

logger = logging.getLogger(__name__)


class SqlSkillVersionRepository(SkillVersionRepositoryPort):
    """SQLAlchemy implementation of SkillVersionRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, version: SkillVersion) -> SkillVersion:
        """Create a new skill version snapshot."""
        db_version = DBSkillVersion(
            id=version.id,
            skill_id=version.skill_id,
            version_number=version.version_number,
            version_label=version.version_label,
            skill_md_content=version.skill_md_content,
            resource_files=version.resource_files,
            change_summary=version.change_summary,
            created_by=version.created_by,
            created_at=version.created_at,
        )
        self._session.add(db_version)
        await self._session.flush()
        return version

    async def get_by_version(self, skill_id: str, version_number: int) -> SkillVersion | None:
        """Get a specific version of a skill."""
        query = (
            select(DBSkillVersion)
            .where(DBSkillVersion.skill_id == skill_id)
            .where(DBSkillVersion.version_number == version_number)
        )
        result = await self._session.execute(query)
        db_version = result.scalar_one_or_none()
        return self._to_domain(db_version)

    async def list_by_skill(
        self, skill_id: str, limit: int = 50, offset: int = 0
    ) -> list[SkillVersion]:
        """List all versions of a skill, ordered by version_number DESC."""
        query = (
            select(DBSkillVersion)
            .where(DBSkillVersion.skill_id == skill_id)
            .order_by(DBSkillVersion.version_number.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(query)
        db_versions = result.scalars().all()
        return [self._to_domain(v) for v in db_versions]

    async def get_latest(self, skill_id: str) -> SkillVersion | None:
        """Get the latest version of a skill."""
        query = (
            select(DBSkillVersion)
            .where(DBSkillVersion.skill_id == skill_id)
            .order_by(DBSkillVersion.version_number.desc())
            .limit(1)
        )
        result = await self._session.execute(query)
        db_version = result.scalar_one_or_none()
        return self._to_domain(db_version)

    async def get_max_version_number(self, skill_id: str) -> int:
        """Get the highest version_number for a skill. Returns 0 if none."""
        query = select(func.max(DBSkillVersion.version_number)).where(
            DBSkillVersion.skill_id == skill_id
        )
        result = await self._session.execute(query)
        max_num = result.scalar()
        return max_num or 0

    async def count_by_skill(self, skill_id: str) -> int:
        """Count versions for a skill."""
        query = select(func.count(DBSkillVersion.id)).where(DBSkillVersion.skill_id == skill_id)
        result = await self._session.execute(query)
        return result.scalar() or 0

    def _to_domain(self, db_version: DBSkillVersion | None) -> SkillVersion | None:
        """Convert database model to domain entity."""
        if db_version is None:
            return None
        return SkillVersion(
            id=db_version.id,
            skill_id=db_version.skill_id,
            version_number=db_version.version_number,
            version_label=db_version.version_label,
            skill_md_content=db_version.skill_md_content,
            resource_files=db_version.resource_files or {},
            change_summary=db_version.change_summary,
            created_by=db_version.created_by,
            created_at=db_version.created_at,
        )
