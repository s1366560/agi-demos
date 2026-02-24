"""
V2 SQLAlchemy implementation of SubAgentRepository using BaseRepository.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.subagent import AgentModel, AgentTrigger, SubAgent
from src.domain.ports.repositories.subagent_repository import SubAgentRepositoryPort
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SqlSubAgentRepository(BaseRepository[SubAgent, object], SubAgentRepositoryPort):
    """
    V2 SQLAlchemy implementation of SubAgentRepository using BaseRepository.

    Uses JSON columns to store trigger info and allowed tools/skills.
    Implements tenant-level scoping.
    """

    # This repository doesn't use a standard model for CRUD
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    async def create(self, subagent: SubAgent) -> SubAgent:
        """Create a new subagent."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        db_subagent = DBSubAgent(
            id=subagent.id,
            tenant_id=subagent.tenant_id,
            project_id=subagent.project_id,
            name=subagent.name,
            display_name=subagent.display_name,
            system_prompt=subagent.system_prompt,
            trigger_description=subagent.trigger.description,
            trigger_examples=list(subagent.trigger.examples),
            trigger_keywords=list(subagent.trigger.keywords),
            model=subagent.model.value,
            color=subagent.color,
            allowed_tools=list(subagent.allowed_tools),
            allowed_skills=list(subagent.allowed_skills),
            allowed_mcp_servers=list(subagent.allowed_mcp_servers),
            max_tokens=subagent.max_tokens,
            temperature=subagent.temperature,
            max_iterations=subagent.max_iterations,
            enabled=subagent.enabled,
            total_invocations=subagent.total_invocations,
            avg_execution_time_ms=subagent.avg_execution_time_ms,
            success_rate=subagent.success_rate,
            metadata_json=subagent.metadata,
            created_at=subagent.created_at,
            updated_at=subagent.updated_at,
        )

        self._session.add(db_subagent)
        await self._session.flush()

        return subagent

    async def get_by_id(self, subagent_id: str) -> SubAgent | None:
        """Get a subagent by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        result = await self._session.execute(select(DBSubAgent).where(DBSubAgent.id == subagent_id))
        db_subagent = result.scalar_one_or_none()

        return self._to_domain(db_subagent) if db_subagent else None

    async def get_by_name(
        self,
        tenant_id: str,
        name: str,
    ) -> SubAgent | None:
        """Get a subagent by name within a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        result = await self._session.execute(
            select(DBSubAgent)
            .where(DBSubAgent.tenant_id == tenant_id)
            .where(DBSubAgent.name == name)
        )

        db_subagent = result.scalar_one_or_none()

        return self._to_domain(db_subagent) if db_subagent else None

    async def update(self, subagent: SubAgent) -> SubAgent:
        """Update an existing subagent."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        result = await self._session.execute(select(DBSubAgent).where(DBSubAgent.id == subagent.id))
        db_subagent = result.scalar_one_or_none()

        if not db_subagent:
            raise ValueError(f"SubAgent not found: {subagent.id}")

        # Update fields
        db_subagent.name = subagent.name
        db_subagent.display_name = subagent.display_name
        db_subagent.system_prompt = subagent.system_prompt
        db_subagent.trigger_description = subagent.trigger.description
        db_subagent.trigger_examples = list(subagent.trigger.examples)
        db_subagent.trigger_keywords = list(subagent.trigger.keywords)
        db_subagent.model = subagent.model.value
        db_subagent.color = subagent.color
        db_subagent.allowed_tools = list(subagent.allowed_tools)
        db_subagent.allowed_skills = list(subagent.allowed_skills)
        db_subagent.allowed_mcp_servers = list(subagent.allowed_mcp_servers)
        db_subagent.max_tokens = subagent.max_tokens
        db_subagent.temperature = subagent.temperature
        db_subagent.max_iterations = subagent.max_iterations
        db_subagent.enabled = subagent.enabled
        db_subagent.total_invocations = subagent.total_invocations
        db_subagent.avg_execution_time_ms = subagent.avg_execution_time_ms
        db_subagent.success_rate = subagent.success_rate
        db_subagent.metadata_json = subagent.metadata
        db_subagent.updated_at = subagent.updated_at

        await self._session.flush()

        return subagent

    async def delete(self, subagent_id: str) -> None:
        """Delete a subagent by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        result = await self._session.execute(delete(DBSubAgent).where(DBSubAgent.id == subagent_id))

        if result.rowcount == 0:
            raise ValueError(f"SubAgent not found: {subagent_id}")

    async def list_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[SubAgent]:
        """List all subagents for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        query = select(DBSubAgent).where(DBSubAgent.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(DBSubAgent.enabled.is_(True))

        query = query.order_by(DBSubAgent.created_at.desc()).limit(limit).offset(offset)

        result = await self._session.execute(query)
        db_subagents = result.scalars().all()

        return [self._to_domain(s) for s in db_subagents]

    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str | None = None,
        enabled_only: bool = False,
    ) -> list[SubAgent]:
        """List subagents for a project, including tenant-wide ones (project_id IS NULL).

        When tenant_id is provided, tenant-wide SubAgents are scoped to that tenant.
        """
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        if tenant_id:
            query = select(DBSubAgent).where(
                or_(
                    DBSubAgent.project_id == project_id,
                    (DBSubAgent.project_id.is_(None)) & (DBSubAgent.tenant_id == tenant_id),
                )
            )
        else:
            query = select(DBSubAgent).where(
                or_(DBSubAgent.project_id == project_id, DBSubAgent.project_id.is_(None))
            )

        if enabled_only:
            query = query.where(DBSubAgent.enabled.is_(True))

        query = query.order_by(DBSubAgent.created_at.desc())

        result = await self._session.execute(query)
        db_subagents = result.scalars().all()

        return [self._to_domain(s) for s in db_subagents]

    async def set_enabled(
        self,
        subagent_id: str,
        enabled: bool,
    ) -> SubAgent:
        """Enable or disable a subagent."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        result = await self._session.execute(select(DBSubAgent).where(DBSubAgent.id == subagent_id))
        db_subagent = result.scalar_one_or_none()

        if not db_subagent:
            raise ValueError(f"SubAgent not found: {subagent_id}")

        db_subagent.enabled = enabled
        db_subagent.updated_at = datetime.now(UTC)

        await self._session.flush()

        return self._to_domain(db_subagent)

    async def update_statistics(
        self,
        subagent_id: str,
        execution_time_ms: float,
        success: bool,
    ) -> SubAgent:
        """Update execution statistics for a subagent."""
        subagent = await self.get_by_id(subagent_id)
        if not subagent:
            raise ValueError(f"SubAgent not found: {subagent_id}")

        updated_subagent = subagent.record_execution(execution_time_ms, success)
        return await self.update(updated_subagent)

    async def count_by_tenant(
        self,
        tenant_id: str,
        enabled_only: bool = False,
    ) -> int:
        """Count subagents for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import SubAgent as DBSubAgent

        query = select(func.count(DBSubAgent.id)).where(DBSubAgent.tenant_id == tenant_id)

        if enabled_only:
            query = query.where(DBSubAgent.enabled.is_(True))

        result = await self._session.execute(query)
        return result.scalar() or 0

    async def find_by_keywords(
        self,
        tenant_id: str,
        query: str,
        enabled_only: bool = True,
    ) -> list[SubAgent]:
        """Find subagents by keyword matching."""
        # Get all subagents for the tenant
        subagents = await self.list_by_tenant(tenant_id, enabled_only=enabled_only)

        # Filter by keyword matching
        matching = []
        for subagent in subagents:
            if subagent.trigger.matches_keywords(query):
                matching.append(subagent)

        return matching

    def _to_domain(self, db_subagent: Any) -> SubAgent | None:
        """Convert database model to domain entity."""
        if db_subagent is None:
            return None

        trigger = AgentTrigger(
            description=db_subagent.trigger_description or "",
            examples=list(db_subagent.trigger_examples or []),
            keywords=list(db_subagent.trigger_keywords or []),
        )

        return SubAgent(
            id=db_subagent.id,
            tenant_id=db_subagent.tenant_id,
            project_id=db_subagent.project_id,
            name=db_subagent.name,
            display_name=db_subagent.display_name,
            system_prompt=db_subagent.system_prompt,
            trigger=trigger,
            model=AgentModel(db_subagent.model),
            color=db_subagent.color,
            allowed_tools=list(db_subagent.allowed_tools or ["*"]),
            allowed_skills=list(db_subagent.allowed_skills or []),
            allowed_mcp_servers=list(db_subagent.allowed_mcp_servers or []),
            max_tokens=db_subagent.max_tokens,
            temperature=db_subagent.temperature,
            max_iterations=db_subagent.max_iterations,
            enabled=db_subagent.enabled,
            total_invocations=db_subagent.total_invocations,
            avg_execution_time_ms=db_subagent.avg_execution_time_ms,
            success_rate=db_subagent.success_rate,
            created_at=db_subagent.created_at,
            updated_at=db_subagent.updated_at or db_subagent.created_at,
            metadata=db_subagent.metadata_json,
        )
