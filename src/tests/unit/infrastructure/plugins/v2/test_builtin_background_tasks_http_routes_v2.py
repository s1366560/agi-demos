"""Production V2 ownership tests for the background-tasks HTTP row."""

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
from src.infrastructure.plugins.v2 import builtin_background_tasks_http_routes as subject
from src.infrastructure.plugins.v2.background_task_services import BackgroundTaskPageV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_http_routes import build_builtin_route_graph_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import RouteTableRegistryV2
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

pytestmark = pytest.mark.unit


def test_background_tasks_row_is_a_complete_explicit_v2_contribution() -> None:
    definitions = subject.background_task_route_definitions_v2()

    assert {
        (method, definition.path) for definition in definitions for method in definition.methods
    } == {("GET", "/api/v1/tasks/")}
    assert {definition.owner_entry_id for definition in definitions} == {
        subject.BACKGROUND_TASKS_HTTP_ROUTES_ENTRY_V2
    }
    assert {definition.replaces_builtin_row_id for definition in definitions} == {
        "background-tasks"
    }


def test_background_tasks_row_preserves_route_order_and_openapi() -> None:
    descriptor = PluginGenerationDescriptorV2(
        profile_id="background-task-route-parity",
        generation=1,
        digest="0" * 64,
    )
    claimed = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.background_task_route_definitions_v2(),
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
    assert claimed.v2_owned_row_ids == ("background-tasks",)


async def test_generation_dispatcher_executes_background_tasks_v2_before_static_fallback() -> None:
    services = SimpleNamespace(
        list_tasks=AsyncMock(
            return_value=BackgroundTaskPageV2(
                tasks=({"task_id": "task-a", "status": "running"},),
                total=1,
            )
        )
    )
    authority = SimpleNamespace(services=services)

    async def current_user_override() -> object:
        return SimpleNamespace(id="user-a", is_superuser=False)

    async def background_task_application_override() -> object:
        return authority

    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.background_task_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.background_task_application_authority_dependency_v2: (
                background_task_application_override
            ),
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
    path = "/api/v1/tasks/"

    @outer.get(path)
    async def static_fallback() -> dict[str, str]:
        return {"source": "static"}

    async with (
        pin_operation_context_v2(
            host,
            operation_id="background-task-route-authority",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=outer),
            base_url="http://test",
        ) as client,
    ):
        result = await client.get(path, params={"status": "running", "limit": 7})

    assert result.status_code == 200
    assert result.json() == {
        "tasks": [{"task_id": "task-a", "status": "running"}],
        "total": 1,
    }
    services.list_tasks.assert_awaited_once_with(
        user_id="user-a",
        is_superuser=False,
        status="running",
        limit=7,
    )
    await host.close()


def test_background_tasks_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_background_tasks_http_routes_definition_v2()

    assert definition.module_ref == subject.BACKGROUND_TASKS_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
