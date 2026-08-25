"""Production V2 ownership tests for the tenants HTTP row."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.project_tenant_authority_v2 import (
    project_tenant_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import tenants as tenant_routes
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_tenants_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_tenants_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.tenants_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/tenants/"),
        ("GET", "/api/v1/tenants/"),
        ("GET", "/api/v1/tenants/{tenant_id}"),
        ("PUT", "/api/v1/tenants/{tenant_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/members"),
        ("PATCH", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/members/{user_id}"),
        ("GET", "/api/v1/tenants/{tenant_id}/members"),
        ("GET", "/api/v1/tenants/{tenant_id}/stats"),
        ("GET", "/api/v1/tenants/{tenant_id}/analytics"),
        ("GET", "/api/v1/tenants/{tenant_id}/gene-policies"),
        ("PUT", "/api/v1/tenants/{tenant_id}/gene-policies/{policy_key}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/gene-policies/{policy_key}"),
        ("GET", "/api/v1/tenants/{tenant_id}/registries"),
        ("POST", "/api/v1/tenants/{tenant_id}/registries"),
        ("PUT", "/api/v1/tenants/{tenant_id}/registries/{registry_id}"),
        ("DELETE", "/api/v1/tenants/{tenant_id}/registries/{registry_id}"),
        ("POST", "/api/v1/tenants/{tenant_id}/registries/{registry_id}/test"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.TENANTS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"tenants"}


@pytest.mark.unit
def test_tenants_row_registers_generation_owned_handlers_without_static_db_dependencies() -> None:
    endpoints = {
        definition.name: definition.endpoint
        for definition in subject.tenants_route_definitions_v2()
    }
    expected = {
        "create_tenant": tenant_routes.create_tenant,
        "list_tenants": tenant_routes.list_tenants,
        "get_tenant": tenant_routes.get_tenant,
        "update_tenant": tenant_routes.update_tenant,
        "delete_tenant": tenant_routes.delete_tenant,
        "add_tenant_member": tenant_routes.add_tenant_member,
        "add_tenant_member_json": tenant_routes.add_tenant_member_json,
        "update_tenant_member_role": tenant_routes.update_tenant_member_role,
        "remove_tenant_member": tenant_routes.remove_tenant_member,
        "list_tenant_members": tenant_routes.list_tenant_members,
        "get_tenant_stats": tenant_routes.get_tenant_stats,
        "get_tenant_analytics": tenant_routes.get_tenant_analytics,
        "list_gene_policies": tenant_routes.list_gene_policies,
        "upsert_gene_policy": tenant_routes.upsert_gene_policy,
        "delete_gene_policy": tenant_routes.delete_gene_policy,
        "list_registries": tenant_routes.list_registries,
        "create_registry": tenant_routes.create_registry,
        "update_registry": tenant_routes.update_registry,
        "delete_registry": tenant_routes.delete_registry,
        "test_registry_connection": tenant_routes.test_registry_connection,
    }

    assert endpoints == expected
    for endpoint in expected.values():
        parameters = signature(endpoint).parameters
        assert "db" not in parameters
        authority = parameters["project_tenant"]
        assert authority.default.dependency is project_tenant_authority_dependency_v2


@pytest.mark.unit
def test_tenants_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="tenants-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenants_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("tenants",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_tenants_v2_before_static_fallback() -> None:
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = []
    db = SimpleNamespace(execute=AsyncMock(return_value=rows))

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-1")

    async def project_tenant_override() -> object:
        return SimpleNamespace(db=db)

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.tenants_route_definitions_v2(),
        dependency_overrides={
            tenant_routes.get_current_user: current_user_override,
            project_tenant_authority_dependency_v2: project_tenant_override,
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
    path = "/api/v1/tenants/tenant-1/registries"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="tenants-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json() == []
    db.execute.assert_awaited_once()
    await host.close()


@pytest.mark.unit
def test_tenants_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_tenants_http_routes_definition_v2()

    assert definition.module_ref == subject.TENANTS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
