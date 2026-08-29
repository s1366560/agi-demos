"""Request-lifetime coverage for the Skill repository V2 authority."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.routers import skills
from src.infrastructure.adapters.primary.web.skill_repository_http_application_authority_v2 import (
    skill_repository_http_application_authority_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2, RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "app": FastAPI(),
            "headers": [],
            "method": "POST",
            "path": "/api/v1/skills/",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_pinned_tenant_generation_and_operation_session() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1011,
        version=1011,
    )
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    authority = None
    try:
        async with (
            pin_generation_v2(host),
            skill_repository_http_application_authority_v2(
                request=_request(),
                tenant_id="tenant-a",
                current_user=user,
                db=db,
            ) as authority,
        ):
            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 1011
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.repository._session is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/skills/",
            }

        assert authority is not None
        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        await db.close()
        await host.close()


async def test_authority_fails_closed_without_a_pinned_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.skill_repository_http_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    db = AsyncSession()
    try:
        with pytest.raises(RuntimeV2Error) as error:
            async with skill_repository_http_application_authority_v2(
                request=_request(),
                tenant_id="tenant-a",
                current_user=cast(User, SimpleNamespace(id="user-a")),
                db=db,
            ):
                pass
    finally:
        await db.close()

    assert error.value.code == "generation_not_pinned"


def test_skill_handlers_resolve_repository_only_from_v2_authority() -> None:
    endpoints = (
        skills.create_skill,
        skills.list_skills,
        skills.get_skill,
        skills.update_skill,
        skills.delete_skill,
        skills.update_skill_status,
        skills.list_system_skills,
        skills.get_skill_content,
        skills.update_skill_content,
        skills.import_skill_package,
        skills.import_skill_zip_package,
        skills.export_skill_package,
        skills.apply_skill_evolution_job,
        skills.get_skill_evolution,
        skills.run_skill_evolution,
        skills.list_skill_versions,
        skills.get_skill_version,
        skills.rollback_skill,
    )

    for endpoint in endpoints:
        parameter = signature(endpoint).parameters["skill_repository"]
        assert parameter.default.dependency is skills._get_skill_repository_v2

    assert "get_container_with_db" not in vars(skills)
    assert "DIContainer" not in vars(skills)
