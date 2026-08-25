from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.tenant_skill_config import TenantSkillConfig
from src.infrastructure.adapters.primary.web.routers import tenant_skill_configs as router
from src.infrastructure.adapters.primary.web.tenant_skill_config_application_authority_v2 import (
    TenantSkillConfigApplicationAuthorityV2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.tenant_skill_config_services import (
    TenantSkillConfigApplicationServicesV2,
)


class _FailingTenantSkillConfigRepository:
    async def get_by_tenant_and_skill(self, *_args: object) -> TenantSkillConfig:
        return TenantSkillConfig.create_disable(
            tenant_id="tenant-1",
            system_skill_name="system-skill",
        )

    async def update(self, _config: TenantSkillConfig) -> TenantSkillConfig:
        raise ValueError("TenantSkillConfig not found: config-secret")


class _MissingSkillRepository:
    async def get_by_id(self, _skill_id: str) -> object | None:
        return None


class _PresentSkillRepository:
    async def get_by_id(self, _skill_id: str) -> object:
        return SimpleNamespace(tenant_id="tenant-1")


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


def _authority(
    *,
    db: SimpleNamespace,
    skill_exists: bool = False,
) -> TenantSkillConfigApplicationAuthorityV2:
    skills = _PresentSkillRepository() if skill_exists else _MissingSkillRepository()
    return TenantSkillConfigApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(AsyncSession, db),
        current_user=cast(User, SimpleNamespace(id="user-1")),
        tenant_id="tenant-1",
        services=TenantSkillConfigApplicationServicesV2(
            configs=cast(Any, _FailingTenantSkillConfigRepository()),
            skills=cast(Any, skills),
        ),
    )


@pytest.mark.unit
async def test_selected_tenant_uses_default_when_query_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = AsyncMock()
    monkeypatch.setattr(router, "require_tenant_access", guard)

    resolved = await router._get_selected_tenant_id(
        selected_tenant_id=None,
        fallback_tenant_id="tenant-default",
        current_user=SimpleNamespace(id="user-1"),
        db=SimpleNamespace(),
    )

    assert resolved == "tenant-default"
    guard.assert_not_awaited()


@pytest.mark.unit
async def test_selected_tenant_validates_explicit_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guard = AsyncMock()
    db = SimpleNamespace()
    current_user = SimpleNamespace(id="user-1")
    monkeypatch.setattr(router, "require_tenant_access", guard)

    resolved = await router._get_selected_tenant_id(
        selected_tenant_id="tenant-selected",
        fallback_tenant_id="tenant-default",
        current_user=current_user,
        db=db,
    )

    assert resolved == "tenant-selected"
    guard.assert_awaited_once_with(db, current_user, "tenant-selected")


@pytest.mark.unit
@pytest.mark.parametrize(
    ("call_name", "data"),
    [
        (
            "disable_system_skill",
            router.DisableSkillRequest(system_skill_name="system-skill"),
        ),
        (
            "override_system_skill",
            router.OverrideSkillRequest(
                system_skill_name="system-skill",
                override_skill_id="override-secret",
            ),
        ),
    ],
)
async def test_tenant_skill_config_routes_sanitize_value_errors(
    call_name: str,
    data: object,
    db: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(
            data=data,
            authority=_authority(
                db=db,
                skill_exists=call_name == "override_system_skill",
            ),
        )

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == "Invalid tenant skill config request"
    assert "secret" not in exc_info.value.detail


@pytest.mark.unit
async def test_override_system_skill_sanitizes_missing_override_skill(
    db: SimpleNamespace,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await router.override_system_skill(
            data=router.OverrideSkillRequest(
                system_skill_name="system-skill",
                override_skill_id="override-secret",
            ),
            authority=_authority(db=db),
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Override skill not found"
    assert "secret" not in exc_info.value.detail
