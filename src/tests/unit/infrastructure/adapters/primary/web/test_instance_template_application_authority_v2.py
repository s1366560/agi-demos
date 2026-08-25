"""Request-lifetime coverage for the instance-template V2 authority dependency."""

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
from src.infrastructure.adapters.primary.web.instance_template_application_authority_v2 import (
    InstanceTemplateApplicationAuthorityV2,
    instance_template_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers.instance_templates import (
    add_template_item,
    clone_template,
    create_template,
    delete_template,
    get_template,
    list_template_items,
    list_templates,
    publish_template,
    remove_template_item,
    unpublish_template,
    update_template,
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
_ROUTER_PATH = _ROOT / "src/infrastructure/adapters/primary/web/routers/instance_templates.py"


def _request() -> Request:
    app = FastAPI()
    return Request(
        {
            "type": "http",
            "app": app,
            "headers": [],
            "method": "GET",
            "path": "/api/v1/instance-templates/",
            "path_params": {},
            "query_string": b"",
            "scheme": "http",
            "server": ("test", 80),
        }
    )


async def test_authority_uses_the_pinned_generation_and_disposes_after_the_handler() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=42,
        version=42,
    )
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))
    dependency = None
    authority = None
    try:
        async with pin_generation_v2(host):
            dependency = instance_template_application_authority_dependency_v2(
                request=request,
                current_user=user,
                tenant_id="tenant-a",
                db=db,
            )
            authority = await anext(dependency)

            assert authority.operation.phase is FiberPhaseV2.ACTIVE
            assert authority.operation.descriptor.generation == 42
            assert authority.operation.context.scope.kind is ScopeKindV2.TENANT
            assert authority.operation.context.scope.tenant_id == "tenant-a"
            assert authority.db is db
            assert authority.current_user is user
            assert authority.tenant_id == "tenant-a"
            assert authority.operation.require(OPERATION_DB_SESSION_SERVICE_V2) is db
            assert authority.operation.require(OPERATION_IDENTITY_SERVICE_V2) == {
                "tenant_id": "tenant-a",
                "user_id": "user-a",
            }
            assert authority.operation.require(OPERATION_METADATA_SERVICE_V2) == {
                "kind": "http-authority",
                "method": "GET",
                "path": "/api/v1/instance-templates/",
            }
            assert authority.services.templates._template_repo._session is db
            await dependency.aclose()

        assert authority.operation.phase is FiberPhaseV2.DISPOSED
    finally:
        if dependency is not None:
            await dependency.aclose()
        await db.close()
        await host.close()


async def test_authority_propagates_a_structured_generation_failure_without_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    db = AsyncSession()
    user = cast(User, SimpleNamespace(id="user-a", is_superuser=False))

    def missing_generation() -> Any:
        raise RuntimeV2Error("generation_not_pinned", "test")

    monkeypatch.setattr(
        "src.infrastructure.adapters.primary.web.instance_template_application_authority_v2.current_generation_v2",
        missing_generation,
    )
    dependency = instance_template_application_authority_dependency_v2(
        request=request,
        current_user=user,
        tenant_id="tenant-a",
        db=db,
    )
    try:
        with pytest.raises(RuntimeV2Error) as error:
            await anext(dependency)
    finally:
        await dependency.aclose()
        await db.close()

    assert error.value.code == "generation_not_pinned"


@pytest.mark.parametrize(
    "endpoint",
    [
        create_template,
        list_templates,
        get_template,
        update_template,
        delete_template,
        publish_template,
        unpublish_template,
        clone_template,
        add_template_item,
        remove_template_item,
        list_template_items,
    ],
)
def test_instance_template_routes_require_only_the_v2_authority(endpoint: Any) -> None:
    parameters = signature(endpoint).parameters
    parameter = parameters["authority"]

    assert parameter.default.dependency is instance_template_application_authority_dependency_v2
    assert parameter.annotation in {
        "InstanceTemplateApplicationAuthorityV2",
        InstanceTemplateApplicationAuthorityV2,
    }
    assert "request" not in parameters
    assert "tenant_id" not in parameters
    assert "current_user" not in parameters
    assert "db" not in parameters


def test_router_has_no_static_container_or_template_service_fallback() -> None:
    source = _ROUTER_PATH.read_text(encoding="utf-8")

    assert "DIContainer" not in source
    assert "get_container_with_db" not in source
    assert "app.state.container" not in source
    assert "instance_template_service" not in source
