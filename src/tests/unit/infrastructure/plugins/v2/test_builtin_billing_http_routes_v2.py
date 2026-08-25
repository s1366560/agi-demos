"""Production V2 ownership tests for the tenant billing HTTP row."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.billing_application_authority_v2 import (
    BillingApplicationAuthorityV2,
    billing_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import billing as billing_router
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import User as DBUser
from src.infrastructure.plugins.v2 import builtin_billing_http_routes as subject
from src.infrastructure.plugins.v2.billing_services import BillingApplicationServicesV2
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
def test_billing_row_registers_production_handlers_without_forwarding_wrappers() -> None:
    definitions = subject.billing_route_definitions_v2()

    assert tuple(definition.endpoint for definition in definitions) == (
        billing_router.get_billing_info,
        billing_router.list_invoices,
        billing_router.upgrade_plan,
    )
    assert not hasattr(subject, "get_billing_info_v2")
    assert not hasattr(subject, "list_invoices_v2")
    assert not hasattr(subject, "upgrade_plan_v2")


@pytest.mark.unit
def test_billing_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="billing-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.billing_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("billing",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_billing_v2_before_static_fallback() -> None:
    user = SimpleNamespace(id="user-1")
    db = object()
    calls: list[tuple[object, ...]] = []
    fallback_calls: list[str] = []
    response: dict[str, Any] = {
        "tenant": {"id": "tenant-1", "plan": "pro"},
        "usage": {"projects": 2},
        "invoices": [],
    }

    class BillingService:
        async def get_billing_info(
            self,
            *,
            user_id: str,
            tenant_id: str,
        ) -> dict[str, Any]:
            calls.append(("billing", user_id, tenant_id))
            return response

    authority = BillingApplicationAuthorityV2(
        operation=cast(Any, SimpleNamespace()),
        db=cast(AsyncSession, db),
        current_user=cast(DBUser, user),
        tenant_id="tenant-1",
        services=BillingApplicationServicesV2(billing=cast(Any, BillingService())),
    )

    async def authority_override() -> BillingApplicationAuthorityV2:
        calls.append(("authority", authority.tenant_id, authority.current_user, authority.db))
        return authority

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.billing_route_definitions_v2(),
        dependency_overrides={
            billing_application_authority_dependency_v2: authority_override,
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
        fallback_calls.append(tenant_id)
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
    assert calls == [
        ("authority", "tenant-1", user, db),
        ("billing", "user-1", "tenant-1"),
    ]
    assert fallback_calls == []
    await host.close()


@pytest.mark.unit
def test_billing_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_billing_http_routes_definition_v2()

    assert definition.module_ref == subject.BILLING_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
