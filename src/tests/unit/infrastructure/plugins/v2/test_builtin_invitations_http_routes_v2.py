"""Production V2 ownership tests for the tenant invitations HTTP row."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from starlette.requests import Request

from src.application.schemas.invitation_schemas import InvitationListResponse
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers import invitations as invitation_router
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_invitations_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_invitations_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.invitations_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/tenants/{tenant_id}/invitations"),
        ("GET", "/api/v1/tenants/{tenant_id}/invitations"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/invitations/{invitation_id}"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.INVITATIONS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"invitations"}
    assert tuple(definition.endpoint for definition in definitions) == (
        invitation_router.create_invitation,
        invitation_router.list_pending_invitations,
        invitation_router.cancel_invitation,
    )


@pytest.mark.unit
def test_invitations_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="invitations-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.invitations_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            () if definition.methods == ("WEBSOCKET",) else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("invitations",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_invitations_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[object, ...]] = []
    response = InvitationListResponse(items=[], total=0, limit=25, offset=5)

    class InvitationService:
        async def list_pending(
            self,
            tenant_id: str,
            *,
            limit: int,
            offset: int,
        ) -> tuple[list[object], int]:
            calls.append(("list", tenant_id, limit, offset))
            return [], 0

    @asynccontextmanager
    async def authority_context(**kwargs: object):
        request = cast(Request, kwargs["request"])
        calls.append(
            (
                "authority",
                kwargs["tenant_id"],
                kwargs["current_user"],
                kwargs["db"],
                request.scope["route"].path,
            )
        )
        yield SimpleNamespace(
            db=kwargs["db"],
            current_user=kwargs["current_user"],
            services=SimpleNamespace(invitations=InvitationService()),
        )

    async def allow_admin(*args: object) -> None:
        calls.append(("admin", *args))

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(
        invitation_router,
        "invitation_application_authority_context_v2",
        authority_context,
    )
    monkeypatch.setattr(invitation_router, "_require_invitation_admin", allow_admin)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.invitations_route_definitions_v2(),
        dependency_overrides={
            get_current_user: current_user_override,
            get_db: db_override,
        },
    )
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()
    await registry.publish(distribution.descriptor, graph.table)
    outer = FastAPI()
    outer.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(outer)

    @outer.get("/api/v1/tenants/{tenant_id}/invitations")
    async def static_fallback(tenant_id: str) -> dict[str, str]:
        return {"source": "static", "tenant_id": tenant_id}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="invitations-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(
            "/api/v1/tenants/tenant-1/invitations",
            params={"limit": 25, "offset": 5},
        )

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")
    assert calls == [
        (
            "authority",
            "tenant-1",
            user,
            db,
            "/api/v1/tenants/{tenant_id}/invitations",
        ),
        ("admin", db, user, "tenant-1"),
        ("list", "tenant-1", 25, 5),
    ]
    await host.close()


@pytest.mark.unit
async def test_invitations_v2_handlers_delegate_without_static_router_mount() -> None:
    definitions = subject.invitations_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        invitation_router.create_invitation,
        invitation_router.list_pending_invitations,
        invitation_router.cancel_invitation,
    )
    assert not hasattr(subject, "create_invitation_v2")
    assert not hasattr(subject, "list_pending_invitations_v2")
    assert not hasattr(subject, "cancel_invitation_v2")


@pytest.mark.unit
def test_invitations_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_invitations_http_routes_definition_v2()

    assert definition.module_ref == subject.INVITATIONS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
