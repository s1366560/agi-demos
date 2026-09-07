"""Request-lifetime coverage for the instance/deploy V2 authority dependencies."""

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
from src.infrastructure.adapters.primary.web.instance_deploy_application_authority_v2 import (
    InstanceDeployApplicationAuthorityV2,
    deploy_application_authority_dependency_v2,
    deploy_progress_application_authority_dependency_v2,
    instance_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.deploy import (
    cancel_deploy,
    create_deploy,
    get_deploy,
    get_latest_deploy,
    list_deploys,
    mark_deploy_failed,
    mark_deploy_success,
    stream_deploy_progress,
)
from src.infrastructure.adapters.primary.web.routers.instances import (
    add_member,
    apply_pending_config,
    create_instance,
    delete_instance,
    get_config,
    get_instance,
    get_instance_llm_config,
    list_instances,
    list_members,
    remove_member,
    restart_instance,
    save_pending_config,
    scale_instance,
    search_users,
    update_config,
    update_instance,
    update_instance_llm_config,
    update_member_role,
)
from src.infrastructure.adapters.secondary.persistence.models import User
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_DB_SESSION_SERVICE_V2,
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
    pin_generation_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.runtime import FiberPhaseV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit

_ROOT = Path(__file__).resolve().parents[7]
_INSTANCES_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/instances.py"
_DEPLOY_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/deploy.py"


def _request(path: str) -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": path,
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_instance_authority_pins_a_tenant_generation_until_disposal() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=50,
        version=50,
    )
    request = _request("/api/v1/instances/")
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = instance_application_authority_dependency_v2(
                request=request,
                current_user=user,
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 50
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.current_user is user
            assert authority.tenant_id == "tenant-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2)["path"] == (
                "/api/v1/instances/"
            )
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_deploy_authority_uses_root_scope_until_resource_tenant_is_resolved() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=51,
        version=51,
    )
    request = _request("/api/v1/deploy/deploy-a")
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    dependency = None
    try:
        async with pin_generation_v2(host):
            dependency = deploy_application_authority_dependency_v2(
                request=request,
                current_user=user,
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.context.scope.kind is ScopeKindV2.ROOT
            assert authority.tenant_id is None
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "user_id": "user-a"
            }
            await dependency.aclose()
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


@pytest.mark.parametrize(
    "endpoint",
    [
        create_instance,
        list_instances,
        get_instance,
        update_instance,
        delete_instance,
        scale_instance,
        restart_instance,
        get_config,
        update_config,
        save_pending_config,
        apply_pending_config,
        add_member,
        search_users,
        update_member_role,
        remove_member,
        list_members,
        get_instance_llm_config,
        update_instance_llm_config,
    ],
)
def test_instance_routes_require_only_the_tenant_v2_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["authority"]

    assert parameter.default.dependency is instance_application_authority_dependency_v2
    assert parameter.annotation in {
        "InstanceDeployApplicationAuthorityV2",
        InstanceDeployApplicationAuthorityV2,
    }
    for retired_parameter in ("request", "tenant_id", "current_user", "db"):
        assert retired_parameter not in parameters


@pytest.mark.parametrize(
    "endpoint",
    [
        create_deploy,
        list_deploys,
        get_latest_deploy,
        get_deploy,
        mark_deploy_success,
        mark_deploy_failed,
        cancel_deploy,
    ],
)
def test_deploy_routes_require_only_the_root_v2_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["authority"]

    assert parameter.default.dependency is deploy_application_authority_dependency_v2
    for retired_parameter in ("request", "current_user", "db"):
        assert retired_parameter not in parameters


def test_progress_route_uses_the_header_or_query_v2_authority() -> None:
    parameters = signature(stream_deploy_progress).parameters

    assert parameters["authority"].default.dependency is (
        deploy_progress_application_authority_dependency_v2
    )
    assert "current_user" not in parameters
    assert "db" not in parameters


def test_routers_have_no_static_container_or_repository_fallback() -> None:
    instances_source = _INSTANCES_ROUTER_PATH.read_text(encoding="utf-8")
    deploy_source = _DEPLOY_ROUTER_PATH.read_text(encoding="utf-8")

    for source in (instances_source, deploy_source):
        assert "DIContainer" not in source
        assert "get_container_with_db" not in source
        assert "app.state.container" not in source
    assert "refresh_select_statement" not in instances_source
    assert "UserTenant" not in instances_source
    assert "container.redis_client" not in deploy_source
