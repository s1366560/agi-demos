"""Production V2 ownership tests for the project schema HTTP row."""

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
from src.infrastructure.plugins.v2 import builtin_schema_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit


def test_schema_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.schema_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("GET", "/api/v1/projects/{project_id}/schema/entities"),
        ("POST", "/api/v1/projects/{project_id}/schema/entities"),
        ("PUT", "/api/v1/projects/{project_id}/schema/entities/{entity_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/schema/entities/{entity_id}"),
        ("GET", "/api/v1/projects/{project_id}/schema/edges"),
        ("POST", "/api/v1/projects/{project_id}/schema/edges"),
        ("PUT", "/api/v1/projects/{project_id}/schema/edges/{edge_id}"),
        ("DELETE", "/api/v1/projects/{project_id}/schema/edges/{edge_id}"),
        ("GET", "/api/v1/projects/{project_id}/schema/mappings"),
        ("POST", "/api/v1/projects/{project_id}/schema/mappings"),
        ("DELETE", "/api/v1/projects/{project_id}/schema/mappings/{map_id}"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.SCHEMA_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"schema"}


def test_schema_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="schema-route-parity",
        generation=1,
        digest="0" * 64,
    )
    baseline = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.schema_route_definitions_v2(),
    )

    assert claimed.route_signatures == baseline.route_signatures
    assert (
        claimed.table.openapi_snapshot(descriptor).schema
        == baseline.table.openapi_snapshot(descriptor).schema
    )
    assert claimed.v2_owned_row_ids == ("schema",)


async def test_generation_dispatcher_executes_schema_v2_before_static_fallback() -> None:
    services = SimpleNamespace(list_entity_types=AsyncMock(return_value=[]))
    authority = SimpleNamespace(services=services)

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-a")

    async def schema_application_override() -> object:
        return authority

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.schema_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.schema_application_authority_dependency_v2: schema_application_override,
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
    path = "/api/v1/projects/project-a/schema/entities"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="schema-route-authority",
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
    services.list_entity_types.assert_awaited_once_with(
        user_id="user-a",
        project_id="project-a",
    )
    await host.close()


def test_schema_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_schema_http_routes_definition_v2()

    assert definition.module_ref == subject.SCHEMA_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
