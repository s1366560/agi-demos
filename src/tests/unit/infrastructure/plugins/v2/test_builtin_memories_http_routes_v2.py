"""Production V2 ownership tests for the memories HTTP row."""

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
from src.infrastructure.adapters.primary.web.memory_application_authority_v2 import (
    memory_application_authority_dependency_v2,
)
from src.infrastructure.adapters.primary.web.routers import memories as memory_routes
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.primary.web.workflow_application_authority_v2 import (
    workflow_engine_authority_dependency_v2,
)
from src.infrastructure.plugins.v2 import builtin_memories_http_routes as subject
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
def test_memories_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.memories_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {
        ("POST", "/api/v1/memories/extract-entities"),
        ("POST", "/api/v1/memories/extract-relationships"),
        ("POST", "/api/v1/memories/"),
        ("GET", "/api/v1/memories/"),
        ("GET", "/api/v1/memories/{memory_id}"),
        ("DELETE", "/api/v1/memories/{memory_id}"),
        ("POST", "/api/v1/memories/{memory_id}/reprocess"),
        ("PATCH", "/api/v1/memories/{memory_id}"),
    }
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.MEMORIES_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {"memories"}


@pytest.mark.unit
def test_memories_row_registers_generation_owned_handlers_without_forwarding_wrappers() -> None:
    endpoints = {
        definition.name: definition.endpoint
        for definition in subject.memories_route_definitions_v2()
    }
    expected = {
        "extract_entities": memory_routes.extract_entities,
        "extract_relationships": memory_routes.extract_relationships,
        "create_memory": memory_routes.create_memory,
        "list_memories": memory_routes.list_memories,
        "get_memory": memory_routes.get_memory,
        "delete_memory": memory_routes.delete_memory,
        "reprocess_memory": memory_routes.reprocess_memory,
        "update_memory": memory_routes.update_memory,
    }

    assert endpoints == expected
    for endpoint in expected.values():
        memory_application = signature(endpoint).parameters["memory_application"]
        assert memory_application.default.dependency is memory_application_authority_dependency_v2
    for endpoint_name in ("create_memory", "reprocess_memory", "update_memory"):
        workflow_engine = signature(expected[endpoint_name]).parameters["workflow_engine"]
        assert workflow_engine.default.dependency is workflow_engine_authority_dependency_v2


@pytest.mark.unit
def test_memories_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="memories-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.memories_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("memories",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_memories_v2_before_static_fallback() -> None:
    access_result = MagicMock()
    access_result.scalar_one_or_none.return_value = object()
    count_result = MagicMock()
    count_result.scalar.return_value = 0
    memories_result = MagicMock()
    memories_result.scalars.return_value.all.return_value = []
    db = SimpleNamespace(
        execute=AsyncMock(side_effect=[access_result, count_result, memories_result])
    )
    response = memory_routes.MemoryListResponse(memories=[], total=0, page=2, page_size=15)

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-1")

    async def memory_application_override() -> object:
        return SimpleNamespace(db=db)

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.memories_route_definitions_v2(),
        dependency_overrides={
            memory_routes.get_current_user: current_user_override,
            memory_application_authority_dependency_v2: memory_application_override,
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
    path = "/api/v1/memories/"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="memories-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(
            path,
            params={
                "project_id": "project-1",
                "page": 2,
                "page_size": 15,
                "search": "needle",
                "content_type": "image",
            },
        )

    assert result.status_code == 200
    assert result.json() == response.model_dump(mode="json")
    assert db.execute.await_count == 3
    await host.close()


@pytest.mark.unit
def test_memories_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_memories_http_routes_definition_v2()

    assert definition.module_ref == subject.MEMORIES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
