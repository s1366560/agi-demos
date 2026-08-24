"""Production V2 ownership tests for the memories HTTP row."""

from __future__ import annotations

from typing import Any

import httpx
import pytest
from fastapi import BackgroundTasks, FastAPI

from src.configuration.workspace_core import get_workspace_core_settings
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
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
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("memories",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_memories_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    memory_application = object()
    calls: list[tuple[object, ...]] = []
    response = subject.MemoryListResponse(memories=[], total=0, page=2, page_size=15)

    async def list_handler(*args: object) -> subject.MemoryListResponse:
        calls.append(args)
        return response

    async def current_user_override() -> object:
        return user

    async def memory_application_override() -> object:
        return memory_application

    monkeypatch.setattr(subject, "_list_memories", list_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.memories_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.memory_application_authority_dependency_v2: memory_application_override,
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
    assert calls == [
        ("project-1", 2, 15, "needle", "image", user, memory_application),
    ]
    await host.close()


@pytest.mark.unit
async def test_memories_v2_handlers_preserve_extraction_and_collection_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = {"content": "Remember this"}
    create_body = subject.MemoryCreate(
        project_id="project-1",
        title="Memory",
        content="Remember this",
    )
    background_tasks = BackgroundTasks()
    user = object()
    memory_application = object()
    workflow_engine = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return result

        return call

    monkeypatch.setattr(subject, "_extract_entities", handler("extract-entities"))
    monkeypatch.setattr(subject, "_extract_relationships", handler("extract-relationships"))
    monkeypatch.setattr(subject, "_create_memory", handler("create"))
    monkeypatch.setattr(subject, "_list_memories", handler("list"))

    assert await subject.extract_entities_v2(payload, user, memory_application) is result
    assert await subject.extract_relationships_v2(payload, user, memory_application) is result
    assert (
        await subject.create_memory_v2(
            create_body,
            background_tasks,
            user,
            memory_application,
            workflow_engine,
        )
        is result
    )
    assert (
        await subject.list_memories_v2(
            "project-1",
            2,
            15,
            "needle",
            "image",
            user,
            memory_application,
        )
        is result
    )

    assert calls == [
        ("extract-entities", (payload, user, memory_application)),
        ("extract-relationships", (payload, user, memory_application)),
        (
            "create",
            (create_body, background_tasks, user, memory_application, workflow_engine),
        ),
        (
            "list",
            ("project-1", 2, 15, "needle", "image", user, memory_application),
        ),
    ]


@pytest.mark.unit
async def test_memories_v2_handlers_preserve_item_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_body = subject.MemoryUpdate(version=2, title="Updated")
    background_tasks = BackgroundTasks()
    user = object()
    memory_application = object()
    workflow_engine = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return result

        return call

    monkeypatch.setattr(subject, "_get_memory", handler("get"))
    monkeypatch.setattr(subject, "_delete_memory", handler("delete"))
    monkeypatch.setattr(subject, "_reprocess_memory", handler("reprocess"))
    monkeypatch.setattr(subject, "_update_memory", handler("update"))

    assert await subject.get_memory_v2("memory-1", user, memory_application) is result
    assert await subject.delete_memory_v2("memory-1", user, memory_application) is result
    assert (
        await subject.reprocess_memory_v2(
            "memory-1",
            user,
            workflow_engine,
            memory_application,
        )
        is result
    )
    assert (
        await subject.update_memory_v2(
            "memory-1",
            update_body,
            background_tasks,
            user,
            workflow_engine,
            memory_application,
        )
        is result
    )

    assert calls == [
        ("get", ("memory-1", user, memory_application)),
        ("delete", ("memory-1", user, memory_application)),
        ("reprocess", ("memory-1", user, workflow_engine, memory_application)),
        (
            "update",
            (
                "memory-1",
                update_body,
                background_tasks,
                user,
                workflow_engine,
                memory_application,
            ),
        ),
    ]


@pytest.mark.unit
def test_memories_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_memories_http_routes_definition_v2()

    assert definition.module_ref == subject.MEMORIES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
