"""
V2 SQLAlchemy implementation of TenantSkillConfigRepository using BaseRepository.
"""

import logging
from typing import Any, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.engine import CursorResult

from src.domain.model.agent.tenant_skill_config import (
    TenantSkillAction,
    TenantSkillConfig,
)
from src.domain.ports.repositories.tenant_skill_config_repository import (
    TenantSkillConfigRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SqlTenantSkillConfigRepository(
    BaseRepository[TenantSkillConfig, object], TenantSkillConfigRepositoryPort
):
    """V2 SQLAlchemy implementation of TenantSkillConfigRepository using BaseRepository."""

    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository."""
        super().__init__(session)
        self._session = session

    async def create(self, config: TenantSkillConfig) -> TenantSkillConfig:
        """Create a new tenant skill config."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        db_config = DBConfig(
            id=config.id,
            tenant_id=config.tenant_id,
            system_skill_name=config.system_skill_name,
            action=config.action.value,
            override_skill_id=config.override_skill_id,
            created_at=config.created_at,
            updated_at=config.updated_at,
        )

        self._session.add(db_config)
        await self._session.flush()

        return config

    async def get_by_id(self, config_id: str) -> TenantSkillConfig | None:
        """Get a config by its ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        result = await self._session.execute(select(DBConfig).where(DBConfig.id == config_id))
        db_config = result.scalar_one_or_none()

        return self._to_domain(db_config) if db_config else None

    async def get_by_tenant_and_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> TenantSkillConfig | None:
        """Get a config by tenant and system skill name."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        result = await self._session.execute(
            select(DBConfig)
            .where(DBConfig.tenant_id == tenant_id)
            .where(DBConfig.system_skill_name == system_skill_name)
        )

        db_config = result.scalar_one_or_none()

        return self._to_domain(db_config) if db_config else None

    async def update(self, config: TenantSkillConfig) -> TenantSkillConfig:
        """Update an existing config."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        result = await self._session.execute(select(DBConfig).where(DBConfig.id == config.id))
        db_config = result.scalar_one_or_none()

        if not db_config:
            raise ValueError(f"TenantSkillConfig not found: {config.id}")

        # Update fields
        db_config.action = config.action.value
        db_config.override_skill_id = config.override_skill_id
        db_config.updated_at = config.updated_at

        await self._session.flush()

        return config

    async def delete(self, config_id: str) -> None:
        """Delete a config by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        result = await self._session.execute(delete(DBConfig).where(DBConfig.id == config_id))

        if cast(CursorResult[Any], result).rowcount == 0:
            raise ValueError(f"TenantSkillConfig not found: {config_id}")

    async def delete_by_tenant_and_skill(
        self,
        tenant_id: str,
        system_skill_name: str,
    ) -> None:
        """Delete a config by tenant and system skill name."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        await self._session.execute(
            delete(DBConfig)
            .where(DBConfig.tenant_id == tenant_id)
            .where(DBConfig.system_skill_name == system_skill_name)
        )

    async def list_by_tenant(
        self,
        tenant_id: str,
    ) -> list[TenantSkillConfig]:
        """List all configs for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        query = (
            select(DBConfig)
            .where(DBConfig.tenant_id == tenant_id)
            .order_by(DBConfig.created_at.desc())
        )

        result = await self._session.execute(query)
        db_configs = result.scalars().all()

        return [d for c in db_configs if (d := self._to_domain(c)) is not None]

    async def get_configs_map(
        self,
        tenant_id: str,
    ) -> dict[str, TenantSkillConfig]:
        """Get all configs for a tenant as a map keyed by system_skill_name."""
        configs = await self.list_by_tenant(tenant_id)
        return {c.system_skill_name: c for c in configs}

    async def count_by_tenant(
        self,
        tenant_id: str,
    ) -> int:
        """Count configs for a tenant."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            TenantSkillConfig as DBConfig,
        )

        query = select(func.count(DBConfig.id)).where(DBConfig.tenant_id == tenant_id)

        result = await self._session.execute(query)
        return result.scalar() or 0

    def _to_domain(self, db_config: Any) -> TenantSkillConfig | None:
        """Convert database model to domain entity."""
        if db_config is None:
            return None

        return TenantSkillConfig(
            id=db_config.id,
            tenant_id=db_config.tenant_id,
            system_skill_name=db_config.system_skill_name,
            action=TenantSkillAction(db_config.action),
            override_skill_id=db_config.override_skill_id,
            created_at=db_config.created_at,
            updated_at=db_config.updated_at or db_config.created_at,
        )
