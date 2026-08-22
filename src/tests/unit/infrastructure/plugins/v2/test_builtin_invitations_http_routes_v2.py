"""Production V2 ownership tests for the tenant invitations HTTP row."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from src.application.schemas.invitation_schemas import (
    CreateInvitationRequest,
    InvitationListResponse,
    InvitationResponse,
)
from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
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


@pytest.mark.unit
def test_invitations_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="invitations-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.invitations_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("invitations",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_invitations_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, object, object, int, int]] = []
    response = InvitationListResponse(items=[], total=0, limit=25, offset=5)

    async def list_handler(
        tenant_id: str,
        current_user: object,
        db_value: object,
        limit: int,
        offset: int,
    ) -> InvitationListResponse:
        calls.append((tenant_id, current_user, db_value, limit, offset))
        return response

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_list_pending_invitations", list_handler)
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
    assert calls == [("tenant-1", user, db, 25, 5)]
    await host.close()


@pytest.mark.unit
async def test_invitations_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    body = CreateInvitationRequest(email="invitee@example.com", role="member")
    created = InvitationResponse(
        id="invitation-1",
        tenant_id="tenant-1",
        email=str(body.email),
        role=body.role,
        status="pending",
        invited_by="owner-1",
        expires_at=now,
        created_at=now,
    )
    listed = InvitationListResponse(items=[created], total=1, limit=25, offset=5)
    user = object()
    db = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def create_handler(
        tenant_id: str,
        request_body: CreateInvitationRequest,
        current_user: object,
        db_value: object,
    ) -> InvitationResponse:
        calls.append(("create", (tenant_id, request_body, current_user, db_value)))
        return created

    async def list_handler(
        tenant_id: str,
        current_user: object,
        db_value: object,
        limit: int,
        offset: int,
    ) -> InvitationListResponse:
        calls.append(("list", (tenant_id, current_user, db_value, limit, offset)))
        return listed

    async def cancel_handler(
        tenant_id: str,
        invitation_id: str,
        current_user: object,
        db_value: object,
    ) -> None:
        calls.append(("cancel", (tenant_id, invitation_id, current_user, db_value)))

    monkeypatch.setattr(subject, "_create_invitation", create_handler)
    monkeypatch.setattr(subject, "_list_pending_invitations", list_handler)
    monkeypatch.setattr(subject, "_cancel_invitation", cancel_handler)

    assert (
        await subject.create_invitation_v2(
            tenant_id="tenant-1",
            body=body,
            current_user=user,
            db=db,
        )
        == created
    )
    assert (
        await subject.list_pending_invitations_v2(
            tenant_id="tenant-1",
            current_user=user,
            db=db,
            limit=25,
            offset=5,
        )
        == listed
    )
    assert (
        await subject.cancel_invitation_v2(
            tenant_id="tenant-1",
            invitation_id="invitation-1",
            current_user=user,
            db=db,
        )
        is None
    )
    assert calls == [
        ("create", ("tenant-1", body, user, db)),
        ("list", ("tenant-1", user, db, 25, 5)),
        ("cancel", ("tenant-1", "invitation-1", user, db)),
    ]


@pytest.mark.unit
def test_invitations_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_invitations_http_routes_definition_v2()

    assert definition.module_ref == subject.INVITATIONS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
