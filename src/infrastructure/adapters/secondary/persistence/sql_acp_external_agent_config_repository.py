"""Repository for tenant-scoped ACP external agent configuration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import ACPExternalAgentConfigModel


class ACPExternalAgentConfigRepository:
    """Persist external ACP agent config rows."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_tenant(self, tenant_id: str) -> list[ACPExternalAgentConfigModel]:
        result = await self._session.execute(
            refresh_select_statement(
                select(ACPExternalAgentConfigModel)
                .where(
                    ACPExternalAgentConfigModel.tenant_id == tenant_id,
                    ACPExternalAgentConfigModel.deleted_at.is_(None),
                )
                .order_by(ACPExternalAgentConfigModel.name.asc())
            )
        )
        return list(result.scalars().all())

    async def get_by_tenant_and_key(
        self,
        tenant_id: str,
        agent_key: str,
        *,
        include_deleted: bool = False,
    ) -> ACPExternalAgentConfigModel | None:
        stmt = select(ACPExternalAgentConfigModel).where(
            ACPExternalAgentConfigModel.tenant_id == tenant_id,
            ACPExternalAgentConfigModel.agent_key == agent_key,
        )
        if not include_deleted:
            stmt = stmt.where(ACPExternalAgentConfigModel.deleted_at.is_(None))
        result = await self._session.execute(refresh_select_statement(stmt))
        return result.scalar_one_or_none()

    async def create_or_restore(  # noqa: PLR0913
        self,
        *,
        tenant_id: str,
        agent_key: str,
        name: str,
        transport: str,
        command: str | None,
        args: list[str],
        url: str | None,
        env: dict[str, object],
        headers: dict[str, object],
        enabled: bool,
        runner_pool_key: str | None = None,
        required_labels: Mapping[str, object] | None = None,
        cwd_policy: Mapping[str, object] | None = None,
    ) -> ACPExternalAgentConfigModel:
        existing = await self.get_by_tenant_and_key(
            tenant_id,
            agent_key,
            include_deleted=True,
        )
        if existing is None:
            existing = ACPExternalAgentConfigModel(
                id=ACPExternalAgentConfigModel.generate_id(),
                tenant_id=tenant_id,
                agent_key=agent_key,
                name=name,
                transport=transport,
                command=command,
                args=args,
                url=url,
                env=env,
                headers=headers,
                runner_pool_key=runner_pool_key,
                required_labels=dict(required_labels or {}),
                cwd_policy=dict(cwd_policy or {}),
                enabled=enabled,
            )
            self._session.add(existing)
        else:
            existing.name = name
            existing.transport = transport
            existing.command = command
            existing.args = args
            existing.url = url
            existing.env = env
            existing.headers = headers
            existing.runner_pool_key = runner_pool_key
            existing.required_labels = dict(required_labels or {})
            existing.cwd_policy = dict(cwd_policy or {})
            existing.enabled = enabled
            existing.deleted_at = None
            existing.updated_at = datetime.now(UTC)

        await self._session.flush()
        return existing

    async def update(
        self,
        config: ACPExternalAgentConfigModel,
        *,
        name: str,
        transport: str,
        command: str | None,
        args: list[str],
        url: str | None,
        env: dict[str, object],
        headers: dict[str, object],
        enabled: bool,
        runner_pool_key: str | None = None,
        required_labels: Mapping[str, object] | None = None,
        cwd_policy: Mapping[str, object] | None = None,
    ) -> ACPExternalAgentConfigModel:
        config.name = name
        config.transport = transport
        config.command = command
        config.args = args
        config.url = url
        config.env = env
        config.headers = headers
        config.runner_pool_key = runner_pool_key
        config.required_labels = dict(required_labels or {})
        config.cwd_policy = dict(cwd_policy or {})
        config.enabled = enabled
        config.updated_at = datetime.now(UTC)
        await self._session.flush()
        return config

    async def soft_delete(self, config: ACPExternalAgentConfigModel) -> None:
        config.deleted_at = datetime.now(UTC)
        config.updated_at = datetime.now(UTC)
        await self._session.flush()
