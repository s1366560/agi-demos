"""
V2 SQLAlchemy implementation of TenantAgentConfigRepository using BaseRepository.
"""

import logging
from typing import Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import ConfigType, TenantAgentConfig
from src.domain.ports.repositories.tenant_agent_config_repository import (
    TenantAgentConfigRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class V2SqlTenantAgentConfigRepository(BaseRepository[TenantAgentConfig, object], TenantAgentConfigRepositoryPort):
    """
    V2 SQLAlchemy implementation of TenantAgentConfigRepository using BaseRepository.

    Each tenant has at most one configuration record.
    If no custom config exists, default values are returned.
    """

    # This repository doesn't use a standard model for CRUD
    # We'll implement the methods directly
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    async def get_by_tenant(self, tenant_id: str) -> Optional[TenantAgentConfig]:
        """Get configuration for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantAgentConfig as DBConfig,
        )

        result = await self._session.execute(
            select(DBConfig).where(DBConfig.tenant_id == tenant_id)
        )
        db_config = result.scalar_one_or_none()

        if db_config:
            return self._to_domain(db_config)

        # Return None to indicate no custom config exists
        return None

    async def save(self, config: TenantAgentConfig) -> TenantAgentConfig:
        """Save a configuration (create or update)."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantAgentConfig as DBConfig,
        )

        result = await self._session.execute(
            select(DBConfig).where(DBConfig.tenant_id == config.tenant_id)
        )
        db_config = result.scalar_one_or_none()

        if db_config:
            # Update existing
            db_config.llm_model = config.llm_model
            db_config.llm_temperature = config.llm_temperature
            db_config.pattern_learning_enabled = config.pattern_learning_enabled
            db_config.multi_level_thinking_enabled = config.multi_level_thinking_enabled
            db_config.max_work_plan_steps = config.max_work_plan_steps
            db_config.tool_timeout_seconds = config.tool_timeout_seconds
            db_config.enabled_tools = config.enabled_tools
            db_config.disabled_tools = config.disabled_tools
            db_config.updated_at = config.updated_at
        else:
            # Create new
            db_config = DBConfig(
                id=config.id,
                tenant_id=config.tenant_id,
                llm_model=config.llm_model,
                llm_temperature=config.llm_temperature,
                pattern_learning_enabled=config.pattern_learning_enabled,
                multi_level_thinking_enabled=config.multi_level_thinking_enabled,
                max_work_plan_steps=config.max_work_plan_steps,
                tool_timeout_seconds=config.tool_timeout_seconds,
                enabled_tools=config.enabled_tools,
                disabled_tools=config.disabled_tools,
                created_at=config.created_at,
                updated_at=config.updated_at,
            )
            self._session.add(db_config)

        await self._session.flush()
        await self._session.commit()
        return config

    async def delete(self, tenant_id: str) -> None:
        """Delete configuration for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantAgentConfig as DBConfig,
        )

        result = await self._session.execute(
            delete(DBConfig).where(DBConfig.tenant_id == tenant_id)
        )

        if result.rowcount == 0:
            raise ValueError(f"Configuration not found for tenant: {tenant_id}")

    async def exists(self, tenant_id: str) -> bool:
        """Check if a tenant has custom configuration."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantAgentConfig as DBConfig,
        )

        result = await self._session.execute(
            select(DBConfig.tenant_id).where(DBConfig.tenant_id == tenant_id)
        )

        return result.scalar_one_or_none() is not None

    def _to_domain(self, db_config) -> Optional[TenantAgentConfig]:
        """Convert database model to domain entity."""
        if db_config is None:
            return None

        return TenantAgentConfig(
            id=db_config.id,
            tenant_id=db_config.tenant_id,
            config_type=ConfigType.CUSTOM,
            llm_model=db_config.llm_model,
            llm_temperature=db_config.llm_temperature,
            pattern_learning_enabled=db_config.pattern_learning_enabled,
            multi_level_thinking_enabled=db_config.multi_level_thinking_enabled,
            max_work_plan_steps=db_config.max_work_plan_steps,
            tool_timeout_seconds=db_config.tool_timeout_seconds,
            enabled_tools=db_config.enabled_tools or [],
            disabled_tools=db_config.disabled_tools or [],
            created_at=db_config.created_at,
            updated_at=db_config.updated_at,
        )
