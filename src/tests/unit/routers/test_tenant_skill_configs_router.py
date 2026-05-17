from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException, status

from src.domain.model.agent.tenant_skill_config import TenantSkillConfig
from src.infrastructure.adapters.primary.web.routers import tenant_skill_configs as router


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


class _Container:
    def __init__(self, *, skill_exists: bool = False) -> None:
        self.skill_exists = skill_exists

    def tenant_skill_config_repository(self) -> _FailingTenantSkillConfigRepository:
        return _FailingTenantSkillConfigRepository()

    def skill_repository(self) -> _MissingSkillRepository | _PresentSkillRepository:
        return _PresentSkillRepository() if self.skill_exists else _MissingSkillRepository()


@pytest.fixture(autouse=True)
def failing_container(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(router, "get_container_with_db", lambda *_args: _Container())


@pytest.fixture
def db() -> SimpleNamespace:
    return SimpleNamespace(commit=AsyncMock())


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
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    if call_name == "override_system_skill":
        monkeypatch.setattr(
            router,
            "get_container_with_db",
            lambda *_args: _Container(skill_exists=True),
        )

    with pytest.raises(HTTPException) as exc_info:
        await getattr(router, call_name)(
            request=SimpleNamespace(),
            data=data,
            tenant_id="tenant-1",
            db=db,
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
            request=SimpleNamespace(),
            data=router.OverrideSkillRequest(
                system_skill_name="system-skill",
                override_skill_id="override-secret",
            ),
            tenant_id="tenant-1",
            db=db,
        )

    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert exc_info.value.detail == "Override skill not found"
    assert "secret" not in exc_info.value.detail
