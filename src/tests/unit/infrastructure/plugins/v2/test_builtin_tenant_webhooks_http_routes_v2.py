"""Production V2 ownership tests for the builtin tenant webhooks HTTP row."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from inspect import signature
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.domain.model.tenant.webhook import Webhook
from src.infrastructure.adapters.primary.web.routers import (
    tenant_webhooks as tenant_webhook_routes,
)
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
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
def test_tenant_webhooks_row_registers_generation_owned_handlers_without_wrappers() -> None:
    endpoints = {
        definition.name: definition.endpoint
        for definition in subject.tenant_webhooks_route_definitions_v2()
    }
    expected = {
        "create_webhook": tenant_webhook_routes.create_webhook,
        "list_webhooks": tenant_webhook_routes.list_webhooks,
        "update_webhook": tenant_webhook_routes.update_webhook,
        "delete_webhook": tenant_webhook_routes.delete_webhook,
    }

    assert endpoints == expected
    for endpoint in expected.values():
        parameters = signature(endpoint).parameters
        assert (
            parameters["current_user"].default.dependency is tenant_webhook_routes.get_current_user
        )
        assert parameters["db"].default.dependency is tenant_webhook_routes.get_db


@pytest.mark.unit
def test_tenant_webhooks_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tenant-webhooks-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenant_webhooks_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("tenant-webhooks",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_tenant_webhooks_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = datetime(2026, 8, 22, tzinfo=UTC)
    user = SimpleNamespace(id="user-1")
    db = SimpleNamespace()
    webhook = Webhook(
        id="v2-webhook",
        tenant_id="tenant-1",
        name="V2",
        url="https://example.com/v2",
        secret="redacted-by-handler",
        events=["memory.created"],
        is_active=True,
        created_at=now,
        updated_at=now,
    )
    webhook_service = SimpleNamespace(list_webhooks=AsyncMock(return_value=[webhook]))
    require_tenant_access = AsyncMock()
    context_calls: list[tuple[object, object, str | None, str]] = []

    @asynccontextmanager
    async def authority_context(
        *,
        request: Any,
        current_user: object,
        db: object,
        tenant_id: str | None,
    ) -> AsyncIterator[object]:
        context_calls.append((current_user, db, tenant_id, request.url.path))
        yield SimpleNamespace(
            db=db,
            current_user=current_user,
            services=SimpleNamespace(webhooks=webhook_service),
        )

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(
        tenant_webhook_routes,
        "tenant_webhook_application_authority_context_v2",
        authority_context,
    )
    monkeypatch.setattr(
        tenant_webhook_routes,
        "require_tenant_access",
        require_tenant_access,
    )
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenant_webhooks_route_definitions_v2(),
        dependency_overrides={
            tenant_webhook_routes.get_current_user: current_user_override,
            tenant_webhook_routes.get_db: db_override,
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
    assert response.json()[0]["secret"] is None
    assert context_calls == [(user, db, "tenant-1", "/api/v1/tenant-webhooks/tenant-1")]
    require_tenant_access.assert_awaited_once_with(
        db,
        user,
        "tenant-1",
        require_admin=True,
    )
    webhook_service.list_webhooks.assert_awaited_once_with("tenant-1")
    await host.close()


@pytest.mark.unit
def test_tenant_webhooks_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tenant_webhooks_http_routes_definition_v2()

    assert definition.module_ref == subject.TENANT_WEBHOOKS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
