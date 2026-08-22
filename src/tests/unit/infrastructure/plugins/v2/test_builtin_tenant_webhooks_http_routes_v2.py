"""Production V2 ownership tests for the builtin tenant webhooks HTTP row."""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.dependencies import get_current_user
from src.infrastructure.adapters.primary.web.routers.tenant_webhooks import (
    WebhookCreateRequest,
    WebhookResponse,
    WebhookUpdateRequest,
)
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_tenant_webhooks_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_tenant_webhooks_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.tenant_webhooks_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/tenant-webhooks/{tenant_id}"),
        ("GET", "/api/v1/tenant-webhooks/{tenant_id}"),
        ("PUT", "/api/v1/tenant-webhooks/{webhook_id}"),
        ("DELETE", "/api/v1/tenant-webhooks/{webhook_id}"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TENANT_WEBHOOKS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"tenant-webhooks"}


@pytest.mark.unit
def test_tenant_webhooks_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tenant-webhooks-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenant_webhooks_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("tenant-webhooks",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_tenant_webhooks_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    user = object()
    db = object()
    calls: list[tuple[str, object, object, object]] = []

    async def list_handler(
        tenant_id: str,
        request: object,
        current_user: object,
        db_value: object,
    ) -> list[WebhookResponse]:
        calls.append((tenant_id, request, current_user, db_value))
        return [
            WebhookResponse(
                id="v2-webhook",
                tenant_id=tenant_id,
                name="V2",
                url="https://example.com/v2",
                secret=None,
                events=["memory.created"],
                is_active=True,
                created_at=now,
                updated_at=now,
            )
        ]

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_list_webhooks", list_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenant_webhooks_route_definitions_v2(),
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

    @outer.get("/api/v1/tenant-webhooks/{tenant_id}")
    async def static_fallback(tenant_id: str) -> dict[str, str]:
        return {"source": "static", "tenant_id": tenant_id}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="tenant-webhooks-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/v1/tenant-webhooks/tenant-1")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "v2-webhook"
    assert len(calls) == 1
    assert calls[0][0] == "tenant-1"
    assert calls[0][2:] == (user, db)
    await host.close()


@pytest.mark.unit
async def test_tenant_webhooks_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    create_body = WebhookCreateRequest(
        name="Deploy",
        url="https://example.com/create",
        events=["memory.created"],
        is_active=True,
    )
    update_body = WebhookUpdateRequest(
        name="Deploy updated",
        url="https://example.com/update",
        events=["memory.updated"],
        is_active=False,
    )
    created = WebhookResponse(
        id="webhook-1",
        tenant_id="tenant-1",
        name=create_body.name,
        url=create_body.url,
        secret="secret-on-create",
        events=create_body.events,
        is_active=create_body.is_active,
        created_at=now,
        updated_at=now,
    )
    listed = [created.model_copy(update={"secret": None})]
    updated = created.model_copy(
        update={
            "name": update_body.name,
            "url": update_body.url,
            "secret": None,
            "events": update_body.events,
            "is_active": update_body.is_active,
        }
    )
    request = object()
    user = object()
    db = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def create_handler(
        tenant_id: str,
        body: WebhookCreateRequest,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> WebhookResponse:
        calls.append(("create", (tenant_id, body, request_value, current_user, db_value)))
        return created

    async def list_handler(
        tenant_id: str,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> list[WebhookResponse]:
        calls.append(("list", (tenant_id, request_value, current_user, db_value)))
        return listed

    async def update_handler(
        webhook_id: str,
        body: WebhookUpdateRequest,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> WebhookResponse:
        calls.append(("update", (webhook_id, body, request_value, current_user, db_value)))
        return updated

    async def delete_handler(
        webhook_id: str,
        request_value: object,
        current_user: object,
        db_value: object,
    ) -> None:
        calls.append(("delete", (webhook_id, request_value, current_user, db_value)))

    monkeypatch.setattr(subject, "_create_webhook", create_handler)
    monkeypatch.setattr(subject, "_list_webhooks", list_handler)
    monkeypatch.setattr(subject, "_update_webhook", update_handler)
    monkeypatch.setattr(subject, "_delete_webhook", delete_handler)

    assert (
        await subject.create_webhook_v2(
            tenant_id="tenant-1",
            body=create_body,
            request=request,
            current_user=user,
            db=db,
        )
        == created
    )
    assert (
        await subject.list_webhooks_v2(
            tenant_id="tenant-1",
            request=request,
            current_user=user,
            db=db,
        )
        == listed
    )
    assert (
        await subject.update_webhook_v2(
            webhook_id="webhook-1",
            body=update_body,
            request=request,
            current_user=user,
            db=db,
        )
        == updated
    )
    assert (
        await subject.delete_webhook_v2(
            webhook_id="webhook-1",
            request=request,
            current_user=user,
            db=db,
        )
        is None
    )
    assert calls == [
        ("create", ("tenant-1", create_body, request, user, db)),
        ("list", ("tenant-1", request, user, db)),
        ("update", ("webhook-1", update_body, request, user, db)),
        ("delete", ("webhook-1", request, user, db)),
    ]


@pytest.mark.unit
def test_tenant_webhooks_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tenant_webhooks_http_routes_definition_v2()

    assert definition.module_ref == subject.TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
