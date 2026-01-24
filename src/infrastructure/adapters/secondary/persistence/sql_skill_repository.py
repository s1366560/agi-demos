"""
SQLAlchemy implementation of SkillRepository.

Provides persistence for skills with three-level scoping
(system, tenant, project) for multi-tenant isolation.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus, TriggerPattern, TriggerType
from src.domain.model.agent.skill_source import SkillSource
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort

logger = logging.getLogger(__name__)


class SQLSkillRepository(SkillRepositoryPort):
    """
    SQLAlchemy implementation of SkillRepository.

    Uses JSON columns to store trigger patterns and metadata.
    Implements three-level scoping (system, tenant, project).
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        db_skill = DBSkill(
            id=skill.id,
            tenant_id=skill.tenant_id,
            project_id=skill.project_id,
            name=skill.name,
            description=skill.description,
            trigger_type=skill.trigger_type.value,
            trigger_patterns=[p.to_dict() for p in skill.trigger_patterns],
            tools=list(skill.tools),
            prompt_template=skill.prompt_template,
            status=skill.status.value,
            success_count=skill.success_count,
            failure_count=skill.failure_count,
            metadata_json=skill.metadata,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            scope=skill.scope.value,
            is_system_skill=skill.is_system_skill,
            full_content=skill.full_content,
        )

        self._session.add(db_skill)
        await self._session.flush()

        return skill

    async def get_by_id(self, skill_id: str) -> Optional[Skill]:
        """Get a skill by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        result = await self._session.execute(select(DBSkill).where(DBSkill.id == skill_id))
        db_skill = result.scalar_one_or_none()

        return self._to_domain(db_skill) if db_skill else None

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: Optional[SkillScope] = None,
    ) -> Optional[Skill]:
        """Get a skill by name within a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        query = select(DBSkill).where(DBSkill.tenant_id == tenant_id).where(DBSkill.name == name)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        result = await self._session.execute(query)

        db_skill = result.scalar_one_or_none()

        return self._to_domain(db_skill) if db_skill else None

    async def update(self, skill: Skill) -> Skill:
        """Update an existing skill."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        result = await self._session.execute(select(DBSkill).where(DBSkill.id == skill.id))
        db_skill = result.scalar_one_or_none()

        if not db_skill:
            raise ValueError(f"Skill not found: {skill.id}")

        # Update fields
        db_skill.name = skill.name
        db_skill.description = skill.description
        db_skill.trigger_type = skill.trigger_type.value
        db_skill.trigger_patterns = [p.to_dict() for p in skill.trigger_patterns]
        db_skill.tools = list(skill.tools)
        db_skill.prompt_template = skill.prompt_template
        db_skill.status = skill.status.value
        db_skill.success_count = skill.success_count
        db_skill.failure_count = skill.failure_count
        db_skill.metadata_json = skill.metadata
        db_skill.updated_at = skill.updated_at
        db_skill.scope = skill.scope.value
        db_skill.is_system_skill = skill.is_system_skill
        db_skill.full_content = skill.full_content

        await self._session.flush()

        return skill

    async def delete(self, skill_id: str) -> None:
        """Delete a skill by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        result = await self._session.execute(delete(DBSkill).where(DBSkill.id == skill_id))

        if result.rowcount == 0:
            raise ValueError(f"Skill not found: {skill_id}")

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: Optional[SkillStatus] = None,
        scope: Optional[SkillScope] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Skill]:
        """List all skills for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        query = select(DBSkill).where(DBSkill.tenant_id == tenant_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        query = query.order_by(DBSkill.created_at.desc()).limit(limit).offset(offset)

        result = await self._session.execute(query)
        db_skills = result.scalars().all()

        return [self._to_domain(s) for s in db_skills]

    async def list_by_project(
        self,
        project_id: str,
        status: Optional[SkillStatus] = None,
        scope: Optional[SkillScope] = None,
    ) -> List[Skill]:
        """List all skills for a specific project."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        query = select(DBSkill).where(DBSkill.project_id == project_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        query = query.order_by(DBSkill.created_at.desc())

        result = await self._session.execute(query)
        db_skills = result.scalars().all()

        return [self._to_domain(s) for s in db_skills]

    async def find_matching_skills(
        self,
        tenant_id: str,
        query: str,
        threshold: float = 0.5,
        limit: int = 5,
    ) -> List[Skill]:
        """Find skills that match a query."""
        # Get all active skills for the tenant
        skills = await self.list_by_tenant(tenant_id, status=SkillStatus.ACTIVE, limit=100)

        # Calculate match scores
        scored_skills = []
        for skill in skills:
            score = skill.matches_query(query)
            if score >= threshold:
                scored_skills.append((skill, score))

        # Sort by score descending and limit
        scored_skills.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in scored_skills[:limit]]

    async def increment_usage(
        self,
        skill_id: str,
        success: bool,
    ) -> Skill:
        """Increment usage statistics for a skill."""
        skill = await self.get_by_id(skill_id)
        if not skill:
            raise ValueError(f"Skill not found: {skill_id}")

        updated_skill = skill.record_usage(success)
        return await self.update(updated_skill)

    async def count_by_tenant(
        self,
        tenant_id: str,
        status: Optional[SkillStatus] = None,
        scope: Optional[SkillScope] = None,
    ) -> int:
        """Count skills for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

        query = select(func.count(DBSkill.id)).where(DBSkill.tenant_id == tenant_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        result = await self._session.execute(query)
        return result.scalar() or 0

    def _to_domain(self, db_skill) -> Optional[Skill]:
        """Convert database model to domain entity."""
        if db_skill is None:
            return None

        trigger_patterns = [TriggerPattern.from_dict(p) for p in (db_skill.trigger_patterns or [])]

        # Handle scope field (may not exist in old records)
        scope = SkillScope.TENANT
        if hasattr(db_skill, "scope") and db_skill.scope:
            scope = SkillScope(db_skill.scope)

        # Handle is_system_skill field (may not exist in old records)
        is_system_skill = False
        if hasattr(db_skill, "is_system_skill"):
            is_system_skill = db_skill.is_system_skill or False

        # Handle full_content field (may not exist in old records)
        full_content = None
        if hasattr(db_skill, "full_content"):
            full_content = db_skill.full_content

        return Skill(
            id=db_skill.id,
            tenant_id=db_skill.tenant_id,
            project_id=db_skill.project_id,
            name=db_skill.name,
            description=db_skill.description,
            trigger_type=TriggerType(db_skill.trigger_type),
            trigger_patterns=trigger_patterns,
            tools=list(db_skill.tools or []),
            prompt_template=db_skill.prompt_template,
            status=SkillStatus(db_skill.status),
            success_count=db_skill.success_count,
            failure_count=db_skill.failure_count,
            created_at=db_skill.created_at,
            updated_at=db_skill.updated_at or db_skill.created_at,
            metadata=db_skill.metadata_json,
            source=SkillSource.DATABASE,
            scope=scope,
            is_system_skill=is_system_skill,
            full_content=full_content,
        )
