"""
V2 SQLAlchemy implementation of ProjectSandboxRepository using BaseRepository.
"""

import hashlib
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator, List, Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)
from src.domain.ports.repositories.project_sandbox_repository import (
    ProjectSandboxRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SqlProjectSandboxRepository(BaseRepository[ProjectSandbox, object], ProjectSandboxRepository):
    """V2 SQLAlchemy implementation of ProjectSandboxRepository using BaseRepository."""

    # This repository doesn't use a standard model for CRUD
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    def _to_domain(self, orm) -> ProjectSandbox:
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

    def _to_orm(self, domain: ProjectSandbox):
        """Convert domain entity to ORM model."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.id == association_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def find_by_project(self, project_id: str) -> Optional[ProjectSandbox]:
        """Find the sandbox association for a specific project."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        result = await self._session.execute(
            select(ProjectSandboxORM).where(ProjectSandboxORM.project_id == project_id)
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    async def find_by_sandbox(self, sandbox_id: str) -> Optional[ProjectSandbox]:
        """Find the project association for a specific sandbox."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=max_idle_seconds)

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        orm = await self._session.get(ProjectSandboxORM, association_id)
        if orm:
            await self._session.delete(orm)
            await self._session.commit()
            return True
        return False

    async def delete_by_project(self, project_id: str) -> bool:
        """Delete the sandbox association for a project."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

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

        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        query = select(func.count(ProjectSandboxORM.id)).where(
            ProjectSandboxORM.tenant_id == tenant_id
        )

        if status:
            query = query.where(ProjectSandboxORM.status == status.value)

        result = await self._session.execute(query)
        return result.scalar() or 0

    def _project_lock_id(self, project_id: str) -> int:
        """Generate a stable lock ID for a project.

        PostgreSQL advisory locks use bigint, so we hash the project_id
        to get a consistent numeric identifier.
        """
        # Use first 8 bytes of MD5 hash as lock ID
        hash_bytes = hashlib.md5(f"sandbox_create:{project_id}".encode()).digest()
        # Convert to signed 64-bit integer (PostgreSQL bigint)
        lock_id = int.from_bytes(hash_bytes[:8], byteorder="big", signed=True)
        return lock_id

    async def acquire_project_lock(
        self,
        project_id: str,
        timeout_seconds: int = 30,
        blocking: bool = True,
    ) -> bool:
        """Acquire a distributed lock using PostgreSQL session-level advisory lock.

        IMPORTANT: This is a SESSION-level lock, NOT transaction-level.
        The lock persists until explicitly released or the database connection closes.
        This is critical for protecting long-running operations like Docker container creation.

        Args:
            project_id: The project ID to lock
            timeout_seconds: Timeout for blocking lock (only used if blocking=True)
            blocking: If True, wait for lock; if False, return immediately

        Returns:
            True if lock acquired, False if not (only possible if blocking=False)
        """
        lock_id = self._project_lock_id(project_id)

        # CRITICAL: Ensure transaction is clean before attempting lock operations
        # If a previous operation failed, the transaction is in an aborted state
        # and we need to rollback before we can execute any new SQL
        try:
            await self._session.rollback()
        except Exception:
            # Ignore rollback errors - transaction might already be clean
            pass

        if blocking:
            # pg_advisory_lock blocks until lock is acquired
            # Use lock_timeout to prevent indefinite waiting
            try:
                # Use SET SESSION instead of SET LOCAL since we're managing session-level locks
                # and want the timeout to persist for this session
                await self._session.execute(
                    text(f"SET SESSION lock_timeout = '{timeout_seconds}s'")
                )
                await self._session.execute(
                    text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
                return True
            except Exception as e:
                logger.warning(f"Failed to acquire advisory lock for {project_id}: {e}")
                # CRITICAL: Rollback to clear the aborted transaction state
                # before any further operations on this session
                try:
                    await self._session.rollback()
                except Exception:
                    pass
                # Reset lock timeout to default (0 = no timeout) on failure
                try:
                    await self._session.execute(text("SET SESSION lock_timeout = '0'"))
                except Exception:
                    pass
                return False
        else:
            # pg_try_advisory_lock returns immediately
            try:
                result = await self._session.execute(
                    text("SELECT pg_try_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )
                return result.scalar() or False
            except Exception as e:
                logger.warning(f"Failed to try advisory lock for {project_id}: {e}")
                return False

    async def release_project_lock(self, project_id: str) -> None:
        """Release the session-level distributed lock for a project.

        IMPORTANT: Must be called explicitly after container creation completes.
        Unlike transaction-level locks, session locks persist until released.
        """
        lock_id = self._project_lock_id(project_id)
        try:
            # CRITICAL: Ensure transaction is clean before attempting unlock
            # If a previous operation failed, the transaction is in an aborted state
            try:
                await self._session.rollback()
            except Exception:
                # Ignore rollback errors - transaction might already be clean
                pass

            await self._session.execute(
                text("SELECT pg_advisory_unlock(:lock_id)"),
                {"lock_id": lock_id},
            )
            # Reset lock timeout to default (0 = no timeout)
            try:
                await self._session.execute(text("SET SESSION lock_timeout = '0'"))
            except Exception:
                pass
        except Exception as e:
            logger.warning(f"Failed to release advisory lock for {project_id}: {e}")

    async def find_and_lock_by_project(
        self,
        project_id: str,
    ) -> Optional[ProjectSandbox]:
        """Find sandbox by project with row-level lock (SELECT FOR UPDATE).

        This prevents TOCTOU race conditions by locking the row while checking.
        """
        from src.infrastructure.adapters.secondary.persistence.models import (
            ProjectSandbox as ProjectSandboxORM,
        )

        result = await self._session.execute(
            select(ProjectSandboxORM)
            .where(ProjectSandboxORM.project_id == project_id)
            .with_for_update(nowait=False)  # Wait for lock if held by another tx
        )
        orm = result.scalar_one_or_none()
        return self._to_domain(orm) if orm else None

    @asynccontextmanager
    async def transaction_with_lock(
        self,
        project_id: str,
    ) -> AsyncGenerator[bool, None]:
        """Context manager that acquires advisory lock within a transaction.

        Usage:
            async with repository.transaction_with_lock(project_id) as locked:
                if locked:
                    # Safe to create sandbox
                    ...
                else:
                    # Another process is creating, wait and retry
                    ...
        """
        lock_acquired = await self.acquire_project_lock(project_id)
        try:
            yield lock_acquired
        finally:
            # Lock is auto-released on transaction end
            pass
