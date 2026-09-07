"""Production V2 ownership tests for the data export HTTP row."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2 import builtin_data_export_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit


def test_data_export_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.data_export_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/data/export"),
        ("GET", "/api/v1/data/stats"),
        ("POST", "/api/v1/data/cleanup"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.DATA_EXPORT_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"data-export"}


def test_data_export_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="data-export-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.data_export_route_definitions_v2(),
    )

    assert claimed.route_signatures == tuple(
        (
            definition.path,
            definition.name,
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("data-export",)


async def test_generation_dispatcher_executes_data_export_v2_before_static_fallback() -> None:
    count_stats = AsyncMock(
        return_value={
            "entities": 1,
            "episodes": 2,
            "communities": 3,
            "relationships": 4,
            "total_nodes": 6,
        }
    )
    graph_application = SimpleNamespace(
        db=SimpleNamespace(),
        services=SimpleNamespace(graph_store=SimpleNamespace(count_stats=count_stats)),
    )

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-a", is_superuser=True)

    async def graph_application_override() -> object:
        return graph_application

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.data_export_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.graph_application_authority_dependency_v2: graph_application_override,
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
    path = "/api/v1/data/stats"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="data-export-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path)

    assert result.status_code == 200
    assert result.json()["total_nodes"] == 6
    count_stats.assert_awaited_once_with(tenant_id=None, project_id=None)
    await host.close()


def test_data_export_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_data_export_http_routes_definition_v2()

    assert definition.module_ref == subject.DATA_EXPORT_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
