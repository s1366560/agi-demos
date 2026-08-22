"""Production V2 ownership tests for the tenant billing HTTP row."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.database import get_db
from src.infrastructure.plugins.v2 import builtin_billing_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_billing_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.billing_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/tenants/{tenant_id}/billing"),
        ("GET", "/api/v1/tenants/{tenant_id}/invoices"),
        ("POST", "/api/v1/tenants/{tenant_id}/upgrade"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.BILLING_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"billing"}


@pytest.mark.unit
def test_billing_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="billing-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.billing_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("billing",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_billing_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    calls: list[tuple[str, object, object]] = []
    response: dict[str, Any] = {
        "tenant": {"id": "tenant-1", "plan": "pro"},
        "usage": {"projects": 2},
        "invoices": [],
    }

    async def get_handler(
        tenant_id: str,
        current_user: object,
        db_value: object,
    ) -> dict[str, Any]:
        calls.append((tenant_id, current_user, db_value))
        return response

    async def current_user_override() -> object:
        return user

    async def db_override() -> object:
        return db

    monkeypatch.setattr(subject, "_get_billing_info", get_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.billing_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
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

    @outer.get("/api/v1/tenants/{tenant_id}/billing")
    async def static_fallback(tenant_id: str) -> dict[str, str]:
        return {"source": "static", "tenant_id": tenant_id}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="billing-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get("/api/v1/tenants/tenant-1/billing")

    assert result.status_code == 200
    assert result.json() == response
    assert calls == [("tenant-1", user, db)]
    await host.close()


@pytest.mark.unit
async def test_billing_v2_handlers_delegate_without_static_router_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    db = object()
    plan_data: dict[str, Any] = {"plan": "enterprise"}
    billing = {"tenant": {"id": "tenant-1"}}
    invoices = {"invoices": []}
    upgraded = {"message": "Plan upgraded successfully"}
    calls: list[tuple[str, tuple[object, ...]]] = []

    async def billing_handler(*args: object) -> dict[str, Any]:
        calls.append(("billing", args))
        return billing

    async def invoices_handler(*args: object) -> dict[str, Any]:
        calls.append(("invoices", args))
        return invoices

    async def upgrade_handler(*args: object) -> dict[str, Any]:
        calls.append(("upgrade", args))
        return upgraded

    monkeypatch.setattr(subject, "_get_billing_info", billing_handler)
    monkeypatch.setattr(subject, "_list_invoices", invoices_handler)
    monkeypatch.setattr(subject, "_upgrade_plan", upgrade_handler)

    assert await subject.get_billing_info_v2("tenant-1", user, db) == billing
    assert await subject.list_invoices_v2("tenant-1", user, db) == invoices
    assert await subject.upgrade_plan_v2("tenant-1", plan_data, user, db) == upgraded
    assert calls == [
        ("billing", ("tenant-1", user, db)),
        ("invoices", ("tenant-1", user, db)),
        ("upgrade", ("tenant-1", plan_data, user, db)),
    ]


@pytest.mark.unit
def test_billing_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_billing_http_routes_definition_v2()

    assert definition.module_ref == subject.BILLING_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
