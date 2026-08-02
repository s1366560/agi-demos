"""Transactional revision authority for tenant agent configuration."""

from dataclasses import dataclass
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import (
    ConfigType,
    RuntimeHookConfig,
    TenantAgentConfig,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Tenant,
    TenantAgentConfig as TenantAgentConfigModel,
    TenantAgentConfigAuthority,
)


@dataclass(frozen=True)
class TenantAgentConfigAuthoritySnapshot:
    """Locked configuration state at one authority revision."""

    tenant_id: str
    authority_revision: int
    config: TenantAgentConfig | None
    authority_exists: bool = False


@dataclass(frozen=True)
class TenantAgentConfigAuthorityWrite:
    """Configuration persisted at a new authority revision."""

    config: TenantAgentConfig
    authority_revision: int


class TenantAgentConfigRevisionConflictError(RuntimeError):
    """Raised when a write targets a stale authority revision."""

    def __init__(self, *, expected_revision: int, authority_revision: int) -> None:
        self.expected_revision = expected_revision
        self.authority_revision = authority_revision
        super().__init__(
            "Tenant agent configuration revision conflict: "
            f"expected {expected_revision}, current {authority_revision}"
        )


class SqlTenantAgentConfigAuthorityRepository:
    """Persist tenant config and its revision in one caller-owned transaction."""

    INITIAL_REVISION = 1

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_revision(self, tenant_id: str) -> int:
        """Return the current revision without creating authority state."""
        result = await self._session.execute(
            refresh_select_statement(
                select(TenantAgentConfigAuthority.authority_revision).where(
                    TenantAgentConfigAuthority.tenant_id == tenant_id
                )
            )
        )
        revision = result.scalar_one_or_none()
        return revision if revision is not None else self.INITIAL_REVISION

    async def lock_for_update(
        self,
        tenant_id: str,
        *,
        expected_revision: int,
    ) -> TenantAgentConfigAuthoritySnapshot:
        """Lock the tenant authority and reject stale writers."""
        tenant_result = await self._session.execute(
            refresh_select_statement(
                select(Tenant.id).where(Tenant.id == tenant_id).with_for_update()
            )
        )
        if tenant_result.scalar_one_or_none() is None:
            raise ValueError(f"Tenant not found: {tenant_id}")

        authority_result = await self._session.execute(
            refresh_select_statement(
                select(TenantAgentConfigAuthority)
                .where(TenantAgentConfigAuthority.tenant_id == tenant_id)
                .with_for_update()
            )
        )
        authority = authority_result.scalar_one_or_none()
        authority_revision = (
            authority.authority_revision if authority is not None else self.INITIAL_REVISION
        )
        if expected_revision != authority_revision:
            raise TenantAgentConfigRevisionConflictError(
                expected_revision=expected_revision,
                authority_revision=authority_revision,
            )

        return TenantAgentConfigAuthoritySnapshot(
            tenant_id=tenant_id,
            authority_revision=authority_revision,
            config=await self._get_config_for_update(tenant_id),
            authority_exists=authority is not None,
        )

    async def persist(
        self,
        snapshot: TenantAgentConfigAuthoritySnapshot,
        config: TenantAgentConfig,
    ) -> TenantAgentConfigAuthorityWrite:
        """Persist a full config and advance authority without committing."""
        if snapshot.tenant_id != config.tenant_id:
            raise ValueError("Tenant config authority snapshot does not match config tenant")

        next_revision = snapshot.authority_revision + 1
        await self._persist_config(config)

        if snapshot.authority_exists:
            result = await self._session.execute(
                update(TenantAgentConfigAuthority)
                .where(
                    TenantAgentConfigAuthority.tenant_id == snapshot.tenant_id,
                    TenantAgentConfigAuthority.authority_revision == snapshot.authority_revision,
                )
                .values(authority_revision=next_revision)
            )
            if cast(CursorResult[object], result).rowcount != 1:
                authority_revision = await self.get_revision(snapshot.tenant_id)
                raise TenantAgentConfigRevisionConflictError(
                    expected_revision=snapshot.authority_revision,
                    authority_revision=authority_revision,
                )
        else:
            self._session.add(
                TenantAgentConfigAuthority(
                    tenant_id=snapshot.tenant_id,
                    authority_revision=next_revision,
                )
            )

        await self._session.flush()
        return TenantAgentConfigAuthorityWrite(
            config=config,
            authority_revision=next_revision,
        )

    async def _get_config_for_update(self, tenant_id: str) -> TenantAgentConfig | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(TenantAgentConfigModel)
                .where(TenantAgentConfigModel.tenant_id == tenant_id)
                .with_for_update()
            )
        )
        db_config = result.scalar_one_or_none()
        if db_config is None:
            return None
        return self._to_domain(db_config)

    async def _persist_config(self, config: TenantAgentConfig) -> None:
        result = await self._session.execute(
            refresh_select_statement(
                select(TenantAgentConfigModel)
                .where(TenantAgentConfigModel.tenant_id == config.tenant_id)
                .with_for_update()
            )
        )
        db_config = result.scalar_one_or_none()
        runtime_hooks = [item.to_dict() for item in config.runtime_hooks]
        if db_config is None:
            self._session.add(
                TenantAgentConfigModel(
                    id=config.id,
                    tenant_id=config.tenant_id,
                    llm_model=config.llm_model,
                    llm_temperature=config.llm_temperature,
                    pattern_learning_enabled=config.pattern_learning_enabled,
                    multi_level_thinking_enabled=config.multi_level_thinking_enabled,
                    max_work_plan_steps=config.max_work_plan_steps,
                    tool_timeout_seconds=config.tool_timeout_seconds,
                    enabled_tools=list(config.enabled_tools),
                    disabled_tools=list(config.disabled_tools),
                    runtime_hooks=runtime_hooks,
                    created_at=config.created_at,
                    updated_at=config.updated_at,
                )
            )
            return

        db_config.llm_model = config.llm_model
        db_config.llm_temperature = config.llm_temperature
        db_config.pattern_learning_enabled = config.pattern_learning_enabled
        db_config.multi_level_thinking_enabled = config.multi_level_thinking_enabled
        db_config.max_work_plan_steps = config.max_work_plan_steps
        db_config.tool_timeout_seconds = config.tool_timeout_seconds
        db_config.enabled_tools = list(config.enabled_tools)
        db_config.disabled_tools = list(config.disabled_tools)
        db_config.runtime_hooks = runtime_hooks
        db_config.updated_at = config.updated_at

    @staticmethod
    def _to_domain(db_config: TenantAgentConfigModel) -> TenantAgentConfig:
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
            enabled_tools=list(db_config.enabled_tools or []),
            disabled_tools=list(db_config.disabled_tools or []),
            runtime_hooks=[
                RuntimeHookConfig.from_dict(item)
                for item in (db_config.runtime_hooks or [])
                if isinstance(item, dict)
            ],
            created_at=db_config.created_at,
            updated_at=db_config.updated_at or db_config.created_at,
        )
