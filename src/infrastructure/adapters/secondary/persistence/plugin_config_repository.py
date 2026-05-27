"""Repository for tenant-scoped runtime plugin configuration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import PluginConfigModel


class PluginConfigRepository:
    """Persist runtime plugin config rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_tenant_and_plugin(
        self,
        tenant_id: str,
        plugin_name: str,
    ) -> PluginConfigModel | None:
        """Return a plugin config for one tenant."""
        result = await self._session.execute(
            refresh_select_statement(
                select(PluginConfigModel).where(
                    PluginConfigModel.tenant_id == tenant_id,
                    PluginConfigModel.plugin_name == plugin_name,
                )
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        *,
        tenant_id: str,
        plugin_name: str,
        config: dict[str, object],
    ) -> PluginConfigModel:
        """Create or update a tenant plugin config."""
        existing = await self.get_by_tenant_and_plugin(tenant_id, plugin_name)
        if existing is None:
            existing = PluginConfigModel(
                id=PluginConfigModel.generate_id(),
                tenant_id=tenant_id,
                plugin_name=plugin_name,
                config=config,
            )
            self._session.add(existing)
        else:
            existing.config = config

        await self._session.flush()
        return existing
