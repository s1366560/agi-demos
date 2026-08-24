"""Production V2 ownership tests for the graph stores HTTP row."""

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
            ()
            if definition.methods == ("WEBSOCKET",)
            else tuple(sorted(definition.methods)),
        )
        for definition in claimed.table.definitions
    )
    assert claimed.table.openapi_snapshot(descriptor).schema["openapi"].startswith("3.")
    assert claimed.v2_owned_row_ids == ("graph-stores",)


@pytest.mark.unit
async def test_generation_dispatcher_executes_graph_stores_v2_before_static_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = object()
    backend_store = object()
    calls: list[tuple[object, object]] = []
    response: dict[str, Any] = {"success": True, "data": [{"type": "neo4j"}]}

    async def list_handler(
        current_user: object,
        backend_store_value: object,
    ) -> dict[str, Any]:
        calls.append((current_user, backend_store_value))
        return response

    async def current_user_override() -> object:
        return user

    async def backend_store_override() -> object:
        return backend_store

    monkeypatch.setattr(subject, "_list_store_types", list_handler)
    graph = build_builtin_route_graph_v2(
        workspace_core_settings=get_workspace_core_settings(),
        route_definitions=subject.graph_stores_route_definitions_v2(),
        dependency_overrides={
            subject.get_current_user: current_user_override,
            subject.backend_store_authority_dependency_v2: backend_store_override,
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
    assert calls == [(user, backend_store)]
    await host.close()


@pytest.mark.unit
async def test_graph_stores_v2_handlers_preserve_all_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create_body = subject.StoreCreateRequest(name="Primary graph")
    update_body = subject.StoreUpdateRequest(name="Updated graph")
    test_body = subject.StoreTestRequest(
        engine_type="neo4j",
        connection_config={"uri": "bolt://graph.invalid"},
    )
    user = object()
    backend_store = object()
    result = object()
    calls: list[tuple[str, tuple[object, ...]]] = []

    def handler(name: str, value: object = result) -> Any:
        async def call(*args: object) -> object:
            calls.append((name, args))
            return value

        return call

    monkeypatch.setattr(subject, "_list_store_types", handler("types"))
    monkeypatch.setattr(subject, "_test_store_raw", handler("test-raw"))
    monkeypatch.setattr(subject, "_create_store", handler("create"))
    monkeypatch.setattr(subject, "_list_stores", handler("list"))
    monkeypatch.setattr(subject, "_get_store", handler("get"))
    monkeypatch.setattr(subject, "_update_store", handler("update"))
    monkeypatch.setattr(subject, "_delete_store", handler("delete", None))
    monkeypatch.setattr(subject, "_test_store_by_id", handler("test-by-id"))

    assert await subject.list_store_types_v2(user, backend_store) is result
    assert (
        await subject.test_store_raw_v2(
            test_body,
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )
    assert (
        await subject.create_store_v2(
            create_body,
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )
    assert (
        await subject.list_stores_v2(
            "tenant-query",
            25,
            10,
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )
    assert (
        await subject.get_store_v2(
            "store-1",
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )
    assert (
        await subject.update_store_v2(
            "store-1",
            update_body,
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )
    assert (
        await subject.delete_store_v2(
            "store-1",
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is None
    )
    assert (
        await subject.test_store_by_id_v2(
            "store-1",
            "tenant-query",
            "tenant-fallback",
            user,
            backend_store,
        )
        is result
    )

    assert calls == [
        ("types", (user, backend_store)),
        (
            "test-raw",
            (test_body, "tenant-query", "tenant-fallback", user, backend_store),
        ),
        (
            "create",
            (create_body, "tenant-query", "tenant-fallback", user, backend_store),
        ),
        (
            "list",
            ("tenant-query", 25, 10, "tenant-fallback", user, backend_store),
        ),
        (
            "get",
            ("store-1", "tenant-query", "tenant-fallback", user, backend_store),
        ),
        (
            "update",
            (
                "store-1",
                update_body,
                "tenant-query",
                "tenant-fallback",
                user,
                backend_store,
            ),
        ),
        (
            "delete",
            ("store-1", "tenant-query", "tenant-fallback", user, backend_store),
        ),
        (
            "test-by-id",
            ("store-1", "tenant-query", "tenant-fallback", user, backend_store),
        ),
    ]


@pytest.mark.unit
def test_graph_stores_module_definition_uses_generated_contract_binding() -> None:
    definition = subject.builtin_graph_stores_http_routes_definition_v2()

    assert definition.module_ref == subject.GRAPH_STORES_HTTP_ROUTES_MODULE_V2
    assert definition.contract_digest.startswith("sha256:")
