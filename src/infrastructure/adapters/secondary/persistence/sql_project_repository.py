"""
SQLAlchemy implementation of ProjectRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.project.project import Project
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.infrastructure.adapters.secondary.persistence.models import Project as DBProject

logger = logging.getLogger(__name__)


class SqlAlchemyProjectRepository(ProjectRepository):
    """SQLAlchemy implementation of ProjectRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, project: Project) -> None:
        """Save a project (create or update)"""
        result = await self._session.execute(select(DBProject).where(DBProject.id == project.id))
        db_project = result.scalar_one_or_none()

        if db_project:
            # Update existing project
            db_project.name = project.name
            db_project.description = project.description
            db_project.member_ids = project.member_ids
            db_project.memory_rules = project.memory_rules
            db_project.graph_config = project.graph_config
            db_project.is_public = project.is_public
            db_project.updated_at = project.updated_at
        else:
            # Create new project
            db_project = DBProject(
                id=project.id,
                tenant_id=project.tenant_id,
                name=project.name,
                owner_id=project.owner_id,
                description=project.description,
                member_ids=project.member_ids,
                memory_rules=project.memory_rules,
                graph_config=project.graph_config,
                is_public=project.is_public,
                created_at=project.created_at,
                updated_at=project.updated_at,
            )
            self._session.add(db_project)

        await self._session.flush()

    async def find_by_id(self, project_id: str) -> Optional[Project]:
        """Find a project by ID"""
        result = await self._session.execute(select(DBProject).where(DBProject.id == project_id))
        db_project = result.scalar_one_or_none()
        return self._to_domain(db_project) if db_project else None

    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> List[Project]:
        """List all projects in a tenant"""
        result = await self._session.execute(
            select(DBProject).where(DBProject.tenant_id == tenant_id).offset(offset).limit(limit)
        )
        db_projects = result.scalars().all()
        return [self._to_domain(p) for p in db_projects]

    async def find_by_owner(self, owner_id: str, limit: int = 50, offset: int = 0) -> List[Project]:
        """List all projects owned by a user"""
        result = await self._session.execute(
            select(DBProject).where(DBProject.owner_id == owner_id).offset(offset).limit(limit)
        )
        db_projects = result.scalars().all()
        return [self._to_domain(p) for p in db_projects]

    async def find_public_projects(self, limit: int = 50, offset: int = 0) -> List[Project]:
        """List all public projects"""
        result = await self._session.execute(
            select(DBProject).where(DBProject.is_public).offset(offset).limit(limit)
        )
        db_projects = result.scalars().all()
        return [self._to_domain(p) for p in db_projects]

    async def delete(self, project_id: str) -> None:
        """Delete a project"""
        result = await self._session.execute(select(DBProject).where(DBProject.id == project_id))
        db_project = result.scalar_one_or_none()
        if db_project:
            await self._session.delete(db_project)
            await self._session.flush()

    def _to_domain(self, db_project: DBProject) -> Project:
        """Convert database model to domain model"""
        return Project(
            id=db_project.id,
            tenant_id=db_project.tenant_id,
            name=db_project.name,
            owner_id=db_project.owner_id,
            description=db_project.description,
            member_ids=db_project.member_ids,
            memory_rules=db_project.memory_rules,
            graph_config=db_project.graph_config,
            is_public=db_project.is_public,
            created_at=db_project.created_at,
            updated_at=db_project.updated_at,
        )
