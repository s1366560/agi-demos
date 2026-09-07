"""Production V2 ownership tests for the graph stores HTTP row."""

from __future__ import annotations

from inspect import signature
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.backend_store_authority_v2 import (
    backend_store_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import graph_stores as graph_store_routes
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_graph_stores_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_graph_stores_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.graph_stores_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/graph-stores/types"),
        ("POST", "/api/v1/graph-stores/test"),
        ("POST", "/api/v1/graph-stores"),
        ("GET", "/api/v1/graph-stores"),
        ("GET", "/api/v1/graph-stores/{store_id}"),
        ("PUT", "/api/v1/graph-stores/{store_id}"),
        ("DELETE", "/api/v1/graph-stores/{store_id}"),
        ("POST", "/api/v1/graph-stores/{store_id}/test"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.GRAPH_STORES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"graph-stores"}


@pytest.mark.unit
def test_graph_stores_row_registers_generation_owned_handlers_without_forwarding_wrappers() -> None:
    endpoints = {
        definition.name: definition.endpoint
        for definition in subject.graph_stores_route_definitions_v2()
    }
    expected = {
        "list_store_types": graph_store_routes.list_store_types,
        "test_store_raw": graph_store_routes.test_store_raw,
        "create_store": graph_store_routes.create_store,
        "list_stores": graph_store_routes.list_stores,
        "get_store": graph_store_routes.get_store,
        "update_store": graph_store_routes.update_store,
        "delete_store": graph_store_routes.delete_store,
        "test_store_by_id": graph_store_routes.test_store_by_id,
    }

    assert endpoints == expected
    for endpoint in expected.values():
        backend_store = signature(endpoint).parameters["backend_store"]
        assert backend_store.default.dependency is backend_store_authority_dependency_v2


@pytest.mark.unit
def test_graph_stores_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="graph-stores-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.graph_stores_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("graph-stores",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_graph_stores_v2_before_static_fallback() -> None:
    store_types = [{"type": "neo4j"}]
    graph_service = SimpleNamespace(list_store_types=MagicMock(return_value=store_types))
    backend_store = SimpleNamespace(services=SimpleNamespace(graph_service=graph_service))
    response = {"success": True, "data": store_types}

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-1")

    async def backend_store_override() -> object:
        return backend_store

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.graph_stores_route_definitions_v2(),
        dependency_overrides={
            graph_store_routes.get_current_user: current_user_override,
            backend_store_authority_dependency_v2: backend_store_override,
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
    path = "/api/v1/graph-stores/types"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="graph-stores-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json() == response
    graph_service.list_store_types.assert_called_once_with()
    await host.close()


@pytest.mark.unit
def test_graph_stores_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_graph_stores_http_routes_definition_v2()

    assert definition.module_ref == subject.GRAPH_STORES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
