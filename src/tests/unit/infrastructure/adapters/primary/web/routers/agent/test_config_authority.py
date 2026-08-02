"""Tenant agent configuration revision contract tests."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from src.domain.model.agent.tenant_agent_config import TenantAgentConfig
from src.infrastructure.adapters.primary.web.routers.agent.config import (
    get_tenant_agent_config,
    get_tenant_agent_config_authority_revision,
    update_tenant_agent_config,
)
from src.infrastructure.adapters.primary.web.routers.agent.schemas import (
    UpdateTenantAgentConfigRequest,
)
from src.infrastructure.adapters.secondary.persistence.sql_tenant_agent_config_authority_repository import (
    TenantAgentConfigAuthoritySnapshot,
    TenantAgentConfigAuthorityWrite,
    TenantAgentConfigRevisionConflictError,
)


def _config(*, model: str = "default") -> TenantAgentConfig:
    return TenantAgentConfig.create_default("tenant-1").update_llm_settings(model=model)


@pytest.mark.unit
class TestTenantAgentConfigAuthorityRoutes:
    async def test_get_config_includes_authority_revision(self) -> None:
        config_repository = MagicMock()
        config_repository.get_by_tenant = AsyncMock(return_value=_config())
        authority_repository = MagicMock()
        authority_repository.get_revision = AsyncMock(return_value=7)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.has_tenant_admin_access",
                AsyncMock(return_value=True),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigRepository",
                return_value=config_repository,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigAuthorityRepository",
                return_value=authority_repository,
            ),
        ):
            response = await get_tenant_agent_config(
                request=MagicMock(),
                tenant_id="tenant-1",
                current_user=SimpleNamespace(id="user-1"),
                db=MagicMock(),
            )

        assert response.authority_revision == 7

    async def test_narrow_revision_endpoint_returns_authority(self) -> None:
        authority_repository = MagicMock()
        authority_repository.get_revision = AsyncMock(return_value=4)

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigAuthorityRepository",
                return_value=authority_repository,
            ),
        ):
            response = await get_tenant_agent_config_authority_revision(
                tenant_id="tenant-1",
                current_user=SimpleNamespace(id="user-1"),
                db=MagicMock(),
            )

        assert response.tenant_id == "tenant-1"
        assert response.authority_revision == 4

    async def test_update_commits_config_and_revision_once(self) -> None:
        snapshot = TenantAgentConfigAuthoritySnapshot(
            tenant_id="tenant-1",
            authority_revision=3,
            config=_config(model="openai/gpt-5.4"),
        )
        authority_repository = MagicMock()
        authority_repository.lock_for_update = AsyncMock(return_value=snapshot)
        authority_repository.persist = AsyncMock(
            return_value=TenantAgentConfigAuthorityWrite(
                config=_config(model="anthropic/claude-sonnet-4.5"),
                authority_revision=4,
            )
        )
        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigAuthorityRepository",
                return_value=authority_repository,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ) as invalidate,
        ):
            response = await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(
                    llm_model="anthropic/claude-sonnet-4.5",
                ),
                request=MagicMock(),
                tenant_id="tenant-1",
                expected_revision=3,
                current_user=SimpleNamespace(id="user-1"),
                db=db,
            )

        authority_repository.lock_for_update.assert_awaited_once_with(
            "tenant-1",
            expected_revision=3,
        )
        authority_repository.persist.assert_awaited_once()
        db.commit.assert_awaited_once_with()
        invalidate.assert_called_once_with(tenant_id="tenant-1")
        assert response.authority_revision == 4

    async def test_revision_conflict_is_structured_and_does_not_commit(self) -> None:
        authority_repository = MagicMock()
        authority_repository.lock_for_update = AsyncMock(
            side_effect=TenantAgentConfigRevisionConflictError(
                expected_revision=2,
                authority_revision=5,
            )
        )
        db = MagicMock()
        db.commit = AsyncMock()

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigAuthorityRepository",
                return_value=authority_repository,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ) as invalidate,
            pytest.raises(HTTPException) as exc_info,
        ):
            await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(llm_model="openai/gpt-5.4"),
                request=MagicMock(),
                tenant_id="tenant-1",
                expected_revision=2,
                current_user=SimpleNamespace(id="user-1"),
                db=db,
            )

        assert exc_info.value.status_code == 409
        assert exc_info.value.detail == {
            "reason_code": "tenant_agent_config_revision_conflict",
            "expected_revision": 2,
            "authority_revision": 5,
        }
        db.commit.assert_not_awaited()
        invalidate.assert_not_called()

    async def test_commit_failure_does_not_invalidate_runtime(self) -> None:
        authority_repository = MagicMock()
        authority_repository.lock_for_update = AsyncMock(
            return_value=TenantAgentConfigAuthoritySnapshot(
                tenant_id="tenant-1",
                authority_revision=1,
                config=None,
            )
        )
        authority_repository.persist = AsyncMock(
            return_value=TenantAgentConfigAuthorityWrite(
                config=_config(model="openai/gpt-5.4"),
                authority_revision=2,
            )
        )
        db = MagicMock()
        db.commit = AsyncMock(side_effect=RuntimeError("commit failed"))

        with (
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.require_tenant_access",
                AsyncMock(),
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.SqlTenantAgentConfigAuthorityRepository",
                return_value=authority_repository,
            ),
            patch(
                "src.infrastructure.adapters.primary.web.routers.agent.config.invalidate_agent_session"
            ) as invalidate,
            pytest.raises(HTTPException) as exc_info,
        ):
            await update_tenant_agent_config(
                UpdateTenantAgentConfigRequest(llm_model="openai/gpt-5.4"),
                request=MagicMock(),
                tenant_id="tenant-1",
                expected_revision=1,
                current_user=SimpleNamespace(id="user-1"),
                db=db,
            )

        assert exc_info.value.status_code == 500
        invalidate.assert_not_called()
