"""Request-lifetime coverage for the project/tenant V2 authority dependency."""

from __future__ import annotations

from inspect import signature
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request

from src.domain.model.plugins.generated_v2 import ScopeKindV2
from src.infrastructure.adapters.primary.web.cron_application_authority_v2 import (
    CronApplicationAuthorityV2,
    cron_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    ProjectTenantAuthorityV2,
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.cron import create_cron_job
from src.infrastructure.adapters.primary.web.routers.projects import list_projects
from src.infrastructure.adapters.primary.web.routers.tenants import list_tenants
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

_ROOT = Path(__file__).resolve().parents[7]


def _request() -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "POST",
            "path": "/api/v1/projects/project-a/cron-jobs",
            "path_params": {"project_id": "project-a"},
            "query_string": b"tenant_id=tenant-a",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


@pytest.mark.unit
async def test_authority_uses_the_pinned_generation_and_disposes_after_the_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=6,
        version=6,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = project_tenant_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 6
            assert authority.operation.context.scope.kind is ScopeKindV2.PROJECT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.operation.context.scope.project_id == "project-a"
            assert authority.db is db
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "POST",
                "path": "/api/v1/projects/project-a/cron-jobs",
            }
            assert getattr(authority.services.project_repository, "_session", None) is db
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


@pytest.mark.unit
async def test_authority_propagates_a_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a"))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.project_tenant_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = project_tenant_authority_dependency_v2(
        request=request,
        current_user=user,
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


@pytest.mark.unit
def test_cron_create_route_requires_the_dedicated_v2_authority_dependency() -> None:
    parameter = signature(create_cron_job).parameters["cron_application"]

    assert parameter.default.dependency is cron_application_authority_dependency_v2
    assert parameter.annotation in {"CronApplicationAuthorityV2", CronApplicationAuthorityV2}


@pytest.mark.unit
@pytest.mark.parametrize("endpoint", [list_projects, list_tenants])
def test_project_and_tenant_list_routes_require_v2_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["project_tenant"]

    assert parameter.default.dependency is project_tenant_authority_dependency_v2
    assert parameter.annotation in {"ProjectTenantAuthorityV2", ProjectTenantAuthorityV2}
    assert "db" not in parameters


@pytest.mark.unit
async def test_list_projects_queries_the_v2_authority_session() -> None:
    membership_result = MagicMock()
    membership_result.fetchall.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=membership_result))

    response = await list_projects(
        tenant_id=None,
        page=1,
        page_size=20,
        search=None,
        visibility="all",
        owner_id=None,
        current_user=cast(User, SimpleNamespace(id="user-a")),
        graph_store=None,
        project_tenant=SimpleNamespace(db=db),
        backend_store=SimpleNamespace(services=SimpleNamespace()),
    )

    assert response.projects == []
    assert response.total == 0
    db.execute.assert_awaited_once()


@pytest.mark.unit
async def test_list_tenants_queries_the_v2_authority_session() -> None:
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    tenants_result = MagicMock()
    tenants_result.scalars.return_value.all.return_value = []
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[count_result, tenants_result]),
    )

    response = await list_tenants(
        page=1,
        page_size=20,
        search=None,
        current_user=cast(User, SimpleNamespace(id="user-a")),
        project_tenant=SimpleNamespace(db=db),
    )

    assert response.tenants == []
    assert response.total == 0
    assert db.execute.await_count == 2
