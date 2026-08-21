"""HTTP dependency coverage for the project/tenant V2 shadow seam."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.configuration.di_container import DIContainer
from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.project_tenant_shadow_v2 import (
    PROJECT_TENANT_SHADOW_STATE_V2,
    project_tenant_shadow_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.projects import list_projects
from src.infrastructure.adapters.primary.web.routers.tenants import list_tenants
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import pin_generation_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.project_tenant_services import (
    ProjectTenantShadowEvidenceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[7]


def _request(*, query_string: bytes = b"") -> Request:
    app = FastAPI()
    app.state.container = DIContainer()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/api/v1/projects/",
            "path_params": {},
            "query_string": query_string,
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.unit
async def test_http_shadow_uses_pinned_generation_request_session_and_tenant_scope() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=3,
        version=3,
    )
    request = _request(query_string=b"tenant_id=tenant-a")
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    try:
        async with pin_generation_v2(host):
            evidence = await project_tenant_shadow_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )

        assert evidence.matches is True
        assert evidence.scope.kind is ScopeKindV2.TENANT
        assert evidence.scope.tenant_id == "tenant-a"
        assert evidence.descriptor is not None
        assert evidence.descriptor.generation == 3
        assert getattr(request.state, PROJECT_TENANT_SHADOW_STATE_V2) is evidence
    finally:
        await db.close()
        await host.close()


@pytest.mark.unit
async def test_http_shadow_records_v2_failure_without_changing_route_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.project_tenant_shadow_v2.current_generation_v2",
        missing_generation,
    )
    try:
        evidence = await project_tenant_shadow_dependency_v2(
            request=request,
            current_user=user,
            db=db,
        )
    finally:
        await db.close()

    assert evidence.matches is False
    assert evidence.error_code == "generation_not_pinned"
    assert evidence.differences == ("shadow_execution",)
    assert getattr(request.state, PROJECT_TENANT_SHADOW_STATE_V2) is evidence


@pytest.mark.unit
@pytest.mark.parametrize("endpoint", [list_projects, list_tenants])
def test_project_and_tenant_list_routes_execute_shadow_as_fastapi_dependency(
    endpoint: Any,
) -> None:
    parameter = signature(endpoint).parameters["_project_tenant_shadow"]

    assert parameter.default.dependency is project_tenant_shadow_dependency_v2
    assert parameter.annotation in {
        "ProjectTenantShadowEvidenceV2",
        ProjectTenantShadowEvidenceV2,
    }
