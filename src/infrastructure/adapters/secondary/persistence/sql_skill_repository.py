"""
V2 SQLAlchemy implementation of SkillRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements SkillRepositoryPort interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support

Key Features:
- Three-level scoping for multi-tenant isolation (system, tenant, project)
- JSON storage for trigger patterns and metadata
- Complex filtering by status, scope, tenant, project
- Usage statistics tracking
- Find matching skills with semantic search
"""

import logging
from typing import Any, cast

from sqlalchemy import case, delete, func, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.skill import Skill, SkillScope, SkillStatus
from src.domain.model.agent.skill_source import SkillSource
from src.domain.ports.repositories.skill_repository import SkillRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import Skill as DBSkill

logger = logging.getLogger(__name__)


class SqlSkillRepository(BaseRepository[Skill, DBSkill], SkillRepositoryPort):
    """
    V2 SQLAlchemy implementation of SkillRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    skill-specific query methods and three-level scoping support.
    """

    # Define the SQLAlchemy model class
    _model_class = DBSkill

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (skill-specific operations) ===

    async def create(self, skill: Skill) -> Skill:
        """Create a new skill."""
        db_skill = DBSkill(
            id=skill.id,
            tenant_id=skill.tenant_id,
            project_id=skill.project_id,
            name=skill.name,
            description=skill.description,
            tools=list(skill.tools),
            status=skill.status.value,
            metadata_json=skill.metadata,
            created_at=skill.created_at,
            updated_at=skill.updated_at,
            scope=skill.scope.value,
            is_system_skill=skill.is_system_skill,
            full_content=skill.full_content,
            resource_files=dict(skill.resource_files),
            license=skill.license,
            compatibility=skill.compatibility,
            allowed_tools_raw=skill.allowed_tools_raw,
            spec_version=skill.spec_version,
            current_version=skill.current_version,
            version_label=skill.version_label,
        )

        self._session.add(db_skill)
        await self._session.flush()

        return skill

    async def get_by_id(self, skill_id: str) -> Skill | None:
        """Get a skill by its ID."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBSkill)
                .where(DBSkill.id == skill_id)
                .execution_options(populate_existing=True)
            ))
        )
        db_skill = result.scalar_one_or_none()
        return self._to_domain(db_skill)

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
        scope: SkillScope | None = None,
    ) -> Skill | None:
        """Get a skill by name within a tenant."""
        query = select(DBSkill).where(DBSkill.tenant_id == tenant_id).where(DBSkill.name == name)

        if scope:
            query = query.where(DBSkill.scope == scope.value)
        else:
            query = (
                query.where(DBSkill.project_id.is_(None))
                .order_by(
                    case(
                        (DBSkill.scope == SkillScope.TENANT.value, 0),
                        (DBSkill.scope == SkillScope.SYSTEM.value, 1),
                        else_=2,
                    ),
                    DBSkill.created_at.desc(),
                )
                .limit(1)
            )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query.execution_options(populate_existing=True)))
        )

        db_skill = result.scalars().first() if scope is None else result.scalar_one_or_none()

        return self._to_domain(db_skill)

    async def update(self, skill: Skill) -> Skill:
        """Update an existing skill."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBSkill)
                .where(DBSkill.id == skill.id)
                .execution_options(populate_existing=True)
            ))
        )
        db_skill = result.scalar_one_or_none()

        if not db_skill:
            raise ValueError(f"Skill not found: {skill.id}")

        # Update fields
        db_skill.name = skill.name
        db_skill.description = skill.description
        db_skill.tools = list(skill.tools)
        db_skill.status = skill.status.value
        db_skill.metadata_json = skill.metadata
        db_skill.updated_at = skill.updated_at
        db_skill.scope = skill.scope.value
        db_skill.is_system_skill = skill.is_system_skill
        db_skill.full_content = skill.full_content
        db_skill.resource_files = dict(skill.resource_files)
        db_skill.license = skill.license
        db_skill.compatibility = skill.compatibility
        db_skill.allowed_tools_raw = skill.allowed_tools_raw
        db_skill.spec_version = skill.spec_version
        db_skill.current_version = skill.current_version
        db_skill.version_label = skill.version_label

        await self._session.flush()

        return skill

    async def delete(self, skill_id: str) -> bool:
        """Delete a skill by ID."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(delete(DBSkill).where(DBSkill.id == skill_id)))
        )

        if cast(CursorResult[Any], result).rowcount == 0:
            raise ValueError(f"Skill not found: {skill_id}")
        return True

    async def list_by_tenant(
        self,
        tenant_id: str,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Skill]:
        """List all skills for a tenant."""
        query = select(DBSkill).where(DBSkill.tenant_id == tenant_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        query = query.order_by(DBSkill.created_at.desc()).limit(limit).offset(offset)

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query.execution_options(populate_existing=True)))
        )
        db_skills = result.scalars().all()

        return [d for s in db_skills if (d := self._to_domain(s)) is not None]

    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str | None = None,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
    ) -> list[Skill]:
        """List all skills for a specific project."""
        query = select(DBSkill).where(DBSkill.project_id == project_id)

        if tenant_id:
            query = query.where(DBSkill.tenant_id == tenant_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        query = query.order_by(DBSkill.created_at.desc())

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query.execution_options(populate_existing=True)))
        )
        db_skills = result.scalars().all()

        return [d for s in db_skills if (d := self._to_domain(s)) is not None]

    async def count_by_tenant(
        self,
        tenant_id: str,
        status: SkillStatus | None = None,
        scope: SkillScope | None = None,
    ) -> int:
        """Count skills for a tenant."""
        query = select(func.count(DBSkill.id)).where(DBSkill.tenant_id == tenant_id)

        if status:
            query = query.where(DBSkill.status == status.value)

        if scope:
            query = query.where(DBSkill.scope == scope.value)

        result = await self._session.execute(refresh_select_statement(self._refresh_statement(query)))
        return result.scalar() or 0

    # === Conversion methods ===

    def _to_domain(self, db_skill: DBSkill | None) -> Skill | None:
        """Convert database model to domain entity."""
        if db_skill is None:
            return None

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
        resource_files = {}
        if hasattr(db_skill, "resource_files") and db_skill.resource_files:
            resource_files = dict(db_skill.resource_files)

        # Handle version fields (may not exist in old records)
        current_version = 0
        if hasattr(db_skill, "current_version") and db_skill.current_version is not None:
            current_version = db_skill.current_version

        version_label = None
        if hasattr(db_skill, "version_label"):
            version_label = db_skill.version_label

        return Skill(
            id=db_skill.id,
            tenant_id=db_skill.tenant_id,
            project_id=db_skill.project_id,
            name=db_skill.name,
            description=db_skill.description,
            tools=list(db_skill.tools or []) or ["terminal"],
            status=SkillStatus(db_skill.status),
            created_at=db_skill.created_at,
            updated_at=db_skill.updated_at or db_skill.created_at,
            metadata=db_skill.metadata_json,
            source=SkillSource.DATABASE,
            scope=scope,
            is_system_skill=is_system_skill,
            full_content=full_content,
            resource_files=resource_files,
            license=getattr(db_skill, "license", None),
            compatibility=getattr(db_skill, "compatibility", None),
            allowed_tools_raw=getattr(db_skill, "allowed_tools_raw", None),
            spec_version=getattr(db_skill, "spec_version", None) or "1.0",
            current_version=current_version,
            version_label=version_label,
        )

    def _to_db(self, domain_entity: Skill) -> DBSkill:
        """Convert domain entity to database model."""
        return DBSkill(
            id=domain_entity.id,
            tenant_id=domain_entity.tenant_id,
            project_id=domain_entity.project_id,
            name=domain_entity.name,
            description=domain_entity.description,
            tools=list(domain_entity.tools),
            status=domain_entity.status.value,
            metadata_json=domain_entity.metadata,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            scope=domain_entity.scope.value,
            is_system_skill=domain_entity.is_system_skill,
            full_content=domain_entity.full_content,
            resource_files=dict(domain_entity.resource_files),
            license=domain_entity.license,
            compatibility=domain_entity.compatibility,
            allowed_tools_raw=domain_entity.allowed_tools_raw,
            spec_version=domain_entity.spec_version,
            current_version=domain_entity.current_version,
            version_label=domain_entity.version_label,
        )
