"""
V2 SQLAlchemy implementation of ToolEnvironmentVariableRepository using BaseRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tool_environment_variable import (
    EnvVarScope,
    ToolEnvironmentVariable,
)
from src.domain.ports.repositories.tool_environment_variable_repository import (
    ToolEnvironmentVariableRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class V2SqlToolEnvironmentVariableRepository(BaseRepository[ToolEnvironmentVariable, object], ToolEnvironmentVariableRepositoryPort):
    """
    V2 SQLAlchemy implementation of ToolEnvironmentVariableRepository using BaseRepository.

    Provides CRUD operations for tool environment variables with
    tenant and project-level isolation.
    """

    # This repository doesn't use a standard model for CRUD
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    async def create(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """Create a new environment variable."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        db_record = ToolEnvironmentVariableRecord(
            id=env_var.id,
            tenant_id=env_var.tenant_id,
            project_id=env_var.project_id,
            tool_name=env_var.tool_name,
            variable_name=env_var.variable_name,
            encrypted_value=env_var.encrypted_value,
            description=env_var.description,
            is_required=env_var.is_required,
            is_secret=env_var.is_secret,
            scope=env_var.scope.value,
            created_at=env_var.created_at,
            updated_at=env_var.updated_at,
        )

        self._session.add(db_record)
        await self._session.flush()

        logger.info(
            f"Created env var: {env_var.tool_name}/{env_var.variable_name} "
            f"for tenant={env_var.tenant_id}, project={env_var.project_id}"
        )
        return env_var

    async def get_by_id(self, env_var_id: str) -> Optional[ToolEnvironmentVariable]:
        """Get an environment variable by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        result = await self._session.execute(
            select(ToolEnvironmentVariableRecord).where(
                ToolEnvironmentVariableRecord.id == env_var_id
            )
        )
        db_record = result.scalar_one_or_none()

        return self._to_domain(db_record) if db_record else None

    async def get(
        self,
        tenant_id: str,
        tool_name: str,
        variable_name: str,
        project_id: Optional[str] = None,
    ) -> Optional[ToolEnvironmentVariable]:
        """
        Get an environment variable by tenant, tool, and name.

        If project_id is provided, looks for project-level variable first,
        then falls back to tenant-level.
        """
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        if project_id:
            # First try project-level
            result = await self._session.execute(
                select(ToolEnvironmentVariableRecord).where(
                    ToolEnvironmentVariableRecord.tenant_id == tenant_id,
                    ToolEnvironmentVariableRecord.project_id == project_id,
                    ToolEnvironmentVariableRecord.tool_name == tool_name,
                    ToolEnvironmentVariableRecord.variable_name == variable_name,
                )
            )
            db_record = result.scalar_one_or_none()
            if db_record:
                return self._to_domain(db_record)

        # Fall back to tenant-level (project_id is None)
        result = await self._session.execute(
            select(ToolEnvironmentVariableRecord).where(
                ToolEnvironmentVariableRecord.tenant_id == tenant_id,
                ToolEnvironmentVariableRecord.project_id.is_(None),
                ToolEnvironmentVariableRecord.tool_name == tool_name,
                ToolEnvironmentVariableRecord.variable_name == variable_name,
            )
        )
        db_record = result.scalar_one_or_none()

        return self._to_domain(db_record) if db_record else None

    async def get_for_tool(
        self,
        tenant_id: str,
        tool_name: str,
        project_id: Optional[str] = None,
    ) -> List[ToolEnvironmentVariable]:
        """
        Get all environment variables for a tool.

        Returns merged list with project-level variables overriding
        tenant-level variables with the same name.
        """
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        # Get tenant-level variables
        tenant_query = select(ToolEnvironmentVariableRecord).where(
            ToolEnvironmentVariableRecord.tenant_id == tenant_id,
            ToolEnvironmentVariableRecord.project_id.is_(None),
            ToolEnvironmentVariableRecord.tool_name == tool_name,
        )
        tenant_result = await self._session.execute(tenant_query)
        tenant_vars = {
            r.variable_name: self._to_domain(r) for r in tenant_result.scalars().all()
        }

        if project_id:
            # Get project-level variables and merge (project overrides tenant)
            project_query = select(ToolEnvironmentVariableRecord).where(
                ToolEnvironmentVariableRecord.tenant_id == tenant_id,
                ToolEnvironmentVariableRecord.project_id == project_id,
                ToolEnvironmentVariableRecord.tool_name == tool_name,
            )
            project_result = await self._session.execute(project_query)
            for r in project_result.scalars().all():
                tenant_vars[r.variable_name] = self._to_domain(r)

        return list(tenant_vars.values())

    async def list_by_tenant(
        self,
        tenant_id: str,
        scope: Optional[EnvVarScope] = None,
    ) -> List[ToolEnvironmentVariable]:
        """List all environment variables for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        query = select(ToolEnvironmentVariableRecord).where(
            ToolEnvironmentVariableRecord.tenant_id == tenant_id
        )

        if scope:
            query = query.where(ToolEnvironmentVariableRecord.scope == scope.value)

        query = query.order_by(
            ToolEnvironmentVariableRecord.tool_name,
            ToolEnvironmentVariableRecord.variable_name,
        )

        result = await self._session.execute(query)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def list_by_project(
        self,
        tenant_id: str,
        project_id: str,
    ) -> List[ToolEnvironmentVariable]:
        """List all environment variables for a project."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        query = (
            select(ToolEnvironmentVariableRecord)
            .where(
                ToolEnvironmentVariableRecord.tenant_id == tenant_id,
                ToolEnvironmentVariableRecord.project_id == project_id,
            )
            .order_by(
                ToolEnvironmentVariableRecord.tool_name,
                ToolEnvironmentVariableRecord.variable_name,
            )
        )

        result = await self._session.execute(query)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def update(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """Update an existing environment variable."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        result = await self._session.execute(
            select(ToolEnvironmentVariableRecord).where(
                ToolEnvironmentVariableRecord.id == env_var.id
            )
        )
        db_record = result.scalar_one_or_none()

        if not db_record:
            raise ValueError(f"Environment variable not found: {env_var.id}")

        # Update fields
        db_record.encrypted_value = env_var.encrypted_value
        db_record.description = env_var.description
        db_record.is_required = env_var.is_required
        db_record.is_secret = env_var.is_secret
        db_record.updated_at = env_var.updated_at

        await self._session.flush()

        logger.info(
            f"Updated env var: {env_var.tool_name}/{env_var.variable_name} "
            f"for tenant={env_var.tenant_id}, project={env_var.project_id}"
        )
        return env_var

    async def delete(self, env_var_id: str) -> None:
        """Delete an environment variable by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        result = await self._session.execute(
            delete(ToolEnvironmentVariableRecord).where(
                ToolEnvironmentVariableRecord.id == env_var_id
            )
        )

        if result.rowcount == 0:
            raise ValueError(f"Environment variable not found: {env_var_id}")

        logger.info(f"Deleted env var: {env_var_id}")

    async def delete_by_tool(
        self,
        tenant_id: str,
        tool_name: str,
        project_id: Optional[str] = None,
    ) -> int:
        """Delete all environment variables for a tool."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            ToolEnvironmentVariableRecord,
        )

        conditions = [
            ToolEnvironmentVariableRecord.tenant_id == tenant_id,
            ToolEnvironmentVariableRecord.tool_name == tool_name,
        ]

        if project_id:
            conditions.append(ToolEnvironmentVariableRecord.project_id == project_id)
        else:
            conditions.append(ToolEnvironmentVariableRecord.project_id.is_(None))

        result = await self._session.execute(
            delete(ToolEnvironmentVariableRecord).where(*conditions)
        )

        logger.info(
            f"Deleted {result.rowcount} env vars for tool={tool_name}, "
            f"tenant={tenant_id}, project={project_id}"
        )
        return result.rowcount

    async def upsert(self, env_var: ToolEnvironmentVariable) -> ToolEnvironmentVariable:
        """Create or update an environment variable."""

        # Check if exists
        existing = await self.get(
            tenant_id=env_var.tenant_id,
            tool_name=env_var.tool_name,
            variable_name=env_var.variable_name,
            project_id=env_var.project_id,
        )

        if existing:
            # Update existing
            env_var.id = existing.id  # Preserve original ID
            return await self.update(env_var)
        else:
            # Create new
            return await self.create(env_var)

    async def batch_upsert(
        self,
        env_vars: List[ToolEnvironmentVariable],
    ) -> List[ToolEnvironmentVariable]:
        """Batch create or update environment variables."""
        results = []
        for env_var in env_vars:
            result = await self.upsert(env_var)
            results.append(result)
        return results

    def _to_domain(self, db_record) -> Optional[ToolEnvironmentVariable]:
        """Convert database model to domain entity."""
        if db_record is None:
            return None

        return ToolEnvironmentVariable(
            id=db_record.id,
            tenant_id=db_record.tenant_id,
            project_id=db_record.project_id,
            tool_name=db_record.tool_name,
            variable_name=db_record.variable_name,
            encrypted_value=db_record.encrypted_value,
            description=db_record.description,
            is_required=db_record.is_required,
            is_secret=db_record.is_secret,
            scope=EnvVarScope(db_record.scope),
            created_at=db_record.created_at,
            updated_at=db_record.updated_at,
        )
