"""Tests for tenant agent configuration optimistic-concurrency authority."""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_agent_config import ConfigType, TenantAgentConfig
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_authority_repository import (
    SqlTenantAgentConfigAuthorityRepository,
    TenantAgentConfigRevisionConflictError,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_repository import (
    SqlTenantAgentConfigRepository,
)


def _config(*, tenant_id: str, model: str) -> TenantAgentConfig:
    now = datetime.now(UTC)
    return TenantAgentConfig(
        id=f"tenant-config-{tenant_id}",
        tenant_id=tenant_id,
        config_type=ConfigType.CUSTOM,
        llm_model=model,
        llm_temperature=0.4,
        pattern_learning_enabled=True,
        multi_level_thinking_enabled=True,
        max_work_plan_steps=25,
        tool_timeout_seconds=45,
        enabled_tools=["read_file"],
        disabled_tools=["shell"],
        runtime_hooks=[],
        created_at=now,
        updated_at=now,
    )


@pytest.mark.unit
class TestSqlTenantAgentConfigAuthorityRepository:
    async def test_missing_authority_projects_initial_revision(
        self,
        v2_db_session: AsyncSession,
        workspace_test_seed: dict[str, str],
    ) -> None:
        repository = SqlTenantAgentConfigAuthorityRepository(v2_db_session)

        assert await repository.get_revision(workspace_test_seed["tenant_id"]) == 1

    async def test_persist_advances_revision_without_committing(
        self,
        v2_db_session: AsyncSession,
        workspace_test_seed: dict[str, str],
    ) -> None:
        tenant_id = workspace_test_seed["tenant_id"]
        repository = SqlTenantAgentConfigAuthorityRepository(v2_db_session)
        snapshot = await repository.lock_for_update(tenant_id, expected_revision=1)

        result = await repository.persist(
            snapshot,
            _config(tenant_id=tenant_id, model="openai/gpt-5.4"),
        )

        assert result.authority_revision == 2
        assert result.config.llm_model == "openai/gpt-5.4"
        assert v2_db_session.in_transaction() is True

    async def test_competing_stale_revision_cannot_overwrite_committed_config(
        self,
        v2_db_session: AsyncSession,
        workspace_test_seed: dict[str, str],
    ) -> None:
        tenant_id = workspace_test_seed["tenant_id"]
        repository = SqlTenantAgentConfigAuthorityRepository(v2_db_session)
        snapshot = await repository.lock_for_update(tenant_id, expected_revision=1)
        await repository.persist(
            snapshot,
            _config(tenant_id=tenant_id, model="openai/gpt-5.4"),
        )
        await v2_db_session.commit()

        with pytest.raises(TenantAgentConfigRevisionConflictError) as exc_info:
            await repository.lock_for_update(tenant_id, expected_revision=1)

        assert exc_info.value.expected_revision == 1
        assert exc_info.value.authority_revision == 2
        persisted = await SqlTenantAgentConfigRepository(v2_db_session).get_by_tenant(tenant_id)
        assert persisted is not None
        assert persisted.llm_model == "openai/gpt-5.4"

    async def test_rollback_restores_config_and_revision(
        self,
        v2_db_session: AsyncSession,
        workspace_test_seed: dict[str, str],
    ) -> None:
        tenant_id = workspace_test_seed["tenant_id"]
        repository = SqlTenantAgentConfigAuthorityRepository(v2_db_session)
        initial = await repository.lock_for_update(tenant_id, expected_revision=1)
        await repository.persist(
            initial,
            _config(tenant_id=tenant_id, model="openai/gpt-5.4"),
        )
        await v2_db_session.commit()

        pending = await repository.lock_for_update(tenant_id, expected_revision=2)
        await repository.persist(
            pending,
            _config(tenant_id=tenant_id, model="anthropic/claude-sonnet-4.5"),
        )
        await v2_db_session.rollback()

        assert await repository.get_revision(tenant_id) == 2
        persisted = await SqlTenantAgentConfigRepository(v2_db_session).get_by_tenant(tenant_id)
        assert persisted is not None
        assert persisted.llm_model == "openai/gpt-5.4"
