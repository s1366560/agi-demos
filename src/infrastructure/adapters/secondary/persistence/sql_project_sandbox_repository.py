"""SQLAlchemy implementation of ProjectSandboxRepository."""

from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)
from src.domain.ports.repositories.project_sandbox_repository import (
    ProjectSandboxRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    ProjectSandbox as ProjectSandboxORM,
)


class SqlAlchemyProjectSandboxRepository(ProjectSandboxRepository):
    """SQLAlchemy-based implementation of ProjectSandboxRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    def _to_domain(self, orm: ProjectSandboxORM) -> ProjectSandbox:
        """Convert ORM model to domain entity."""
        return ProjectSandbox(
            id=orm.id,
            project_id=orm.project_id,
            tenant_id=orm.tenant_id,
            sandbox_id=orm.sandbox_id,
            status=ProjectSandboxStatus(orm.status),
            created_at=orm.created_at,
            started_at=orm.started_at,
            last_accessed_at=orm.last_accessed_at,
            health_checked_at=orm.health_checked_at,
            error_message=orm.error_message,
            metadata=orm.metadata_json or {},
        )

    def _to_orm(self, domain: ProjectSandbox) -> ProjectSandboxORM:
        """Convert domain entity to ORM model."""
        return ProjectSandboxORM(
            id=domain.id,
            project_id=domain.project_id,
            tenant_id=domain.tenant_id,
            sandbox_id=domain.sandbox_id,
            status=domain.status.value,
            created_at=domain.created_at,
            started_at=domain.started_at,
            last_accessed_at=domain.last_accessed_at,
            health_checked_at=domain.health_checked_at,
            error_message=domain.error_message,
            metadata_json=domain.metadata,
        )

    async def save(self, association: ProjectSandbox) -> None:
        """Save or update a project-sandbox association."""
        orm = self._to_orm(association)

        # Check if exists
        existing = await self._session.get(ProjectSandboxORM, association.id)
        if existing:
            # Update existing
            existing.project_id = orm.project_id
            existing.tenant_id = orm.tenant_id
            existing.sandbox_id = orm.sandbox_id
            existing.status = orm.status
            existing.started_at = orm.started_at
            existing.last_accessed_at = orm.last_accessed_at
            existing.health_checked_at = orm.health_checked_at
            existing.error_message = orm.error_message
            existing.metadata_json = orm.metadata_json
        else:
            # Insert new
            self._session.add(orm)

        await self._session.commit()

    async def find_by_id(self, association_id: str) -> Optional[ProjectSandbox]:
        """Find a project-sandbox association by its ID."""
        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.id == association_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def find_by_project(self, project_id: str) -> Optional[ProjectSandbox]:
        """Find the sandbox association for a specific project."""
        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.project_id == project_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def find_by_sandbox(self, sandbox_id: str) -> Optional[ProjectSandbox]:
        """Find the project association for a specific sandbox."""
        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.sandbox_id == sandbox_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def find_by_tenant(
        self,
        tenant_id: str,
        status: Optional[ProjectSandboxStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ProjectSandbox]:
        """List all sandbox associations for a tenant."""
        query = select(ProjectSandboxORM).where(ProjectSandboxORM.tenant_id == tenant_id)

        if status:
            query = query.where(ProjectSandboxORM.status == status.value)

        query = query.order_by(ProjectSandboxORM.created_at.desc())
        query = query.offset(offset).limit(limit)

        result = await self._session.execute(query)
        orms = result.scalars().all()
        return [self._to_domain(orm) for orm in orms]

    async def find_by_status(
        self,
        status: ProjectSandboxStatus,
        limit: int = 50,
        offset: int = 0,
    ) -> List[ProjectSandbox]:
        """Find all associations with a specific status."""
        query = (
            select(ProjectSandboxORM)
            .where(ProjectSandboxORM.status == status.value)
            .order_by(ProjectSandboxORM.last_accessed_at.desc())
            .offset(offset)
            .limit(limit)
        )

        result = await self._session.execute(query)
        orms = result.scalars().all()
        return [self._to_domain(orm) for orm in orms]

    async def find_stale(
        self,
        max_idle_seconds: int,
        limit: int = 50,
    ) -> List[ProjectSandbox]:
        """Find associations that haven't been accessed recently."""
        cutoff_time = datetime.utcnow() - timedelta(seconds=max_idle_seconds)

        query = (
            select(ProjectSandboxORM)
            .where(ProjectSandboxORM.last_accessed_at < cutoff_time)
            .where(ProjectSandboxORM.status.in_(["running", "creating"]))
            .order_by(ProjectSandboxORM.last_accessed_at.asc())
            .limit(limit)
        )

        result = await self._session.execute(query)
        orms = result.scalars().all()
        return [self._to_domain(orm) for orm in orms]

    async def delete(self, association_id: str) -> bool:
        """Delete a project-sandbox association."""
        orm = await self._session.get(ProjectSandboxORM, association_id)
        if orm:
            await self._session.delete(orm)
            await self._session.commit()
            return True
        return False

    async def delete_by_project(self, project_id: str) -> bool:
        """Delete the sandbox association for a project."""
        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.project_id == project_id)
        )
        orm = result.scalar_one_or_none()
        if orm:
            await self._session.delete(orm)
            await self._session.commit()
            return True
        return False

    async def exists_for_project(self, project_id: str) -> bool:
        """Check if a project has a sandbox association."""
        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.project_id == project_id)
        )
        return result.scalar_one_or_none() is not None

    async def count_by_tenant(
        self,
        tenant_id: str,
        status: Optional[ProjectSandboxStatus] = None,
    ) -> int:
        """Count sandbox associations for a tenant."""
        from sqlalchemy import func

        query = select(func.count(ProjectSandboxORM.id)).where(
            ProjectSandboxORM.tenant_id == tenant_id
        )

        if status:
            query = query.where(ProjectSandboxORM.status == status.value)

        result = await self._session.execute(query)
        return result.scalar() or 0
