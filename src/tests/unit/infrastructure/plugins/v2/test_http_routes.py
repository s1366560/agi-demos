"""Immutable route table, OpenAPI, and generation dispatch tests."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from pydantic import create_model

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    GenerationRouteDispatcherV2,
    RouteDefinitionV2,
    RouteTableRegistryV2,
    RouteTableV2,
    WebSocketRouteDefinitionV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2

_ROOT = Path(__file__).resolve().parents[6]


def _table(value: str) -> RouteTableV2:
    async def endpoint() -> dict[str, str]:
        return {"generation": value}

    return RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="builtin-http",
                path="/api/value",
                methods=("GET",),
                endpoint=endpoint,
                name=f"value-{value}",
                tags=("Plugin V2",),
            ),
        )
    )


@pytest.mark.unit
def test_route_table_rejects_conflicts_without_mutating_outer_routes() -> None:
    route = _table("one").definitions[0]

    with pytest.raises(RuntimeV2Error) as error:
        RouteTableV2((route, route))

    assert error.value.code == "route_conflict"


@pytest.mark.unit
def test_route_table_supports_http_and_websocket_contributions_at_one_path() -> None:
    async def http_endpoint() -> dict[str, str]:
        return {"transport": "http"}

    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"transport": "websocket"})
        await websocket.close()

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="mixed-transport",
                path="/api/mixed",
                methods=("GET",),
                endpoint=http_endpoint,
                name="mixed-http",
                response_model=dict[str, str],
            ),
            WebSocketRouteDefinitionV2(
                owner_entry_id="mixed-transport",
                path="/api/mixed",
                endpoint=websocket_endpoint,
                name="mixed-websocket",
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="mixed-transport",
        generation=1,
        digest="0" * 64,
    )
    app = FastAPI()
    app.mount("/", table)

    with TestClient(app) as client:
        assert client.get("/api/mixed").json() == {"transport": "http"}
        with client.websocket_connect("/api/mixed") as websocket:
            assert websocket.receive_json() == {"transport": "websocket"}

    assert "/api/mixed" in table.openapi_snapshot(descriptor).schema["paths"]


@pytest.mark.unit
def test_route_table_rejects_duplicate_websocket_contributions() -> None:
    async def websocket_endpoint(_websocket: WebSocket) -> None:
        return None

    route = WebSocketRouteDefinitionV2(
        owner_entry_id="duplicate-websocket",
        path="/api/ws",
        endpoint=websocket_endpoint,
        name="duplicate-websocket",
    )

    with pytest.raises(RuntimeV2Error) as error:
        RouteTableV2((route, route))

    assert error.value.code == "route_conflict"


@pytest.mark.unit
def test_openapi_uses_stable_qualified_names_for_colliding_models() -> None:
    first_payload = create_model(
        "CollisionPayload",
        value=(str, ...),
        __module__="tests.openapi.first",
    )
    second_payload = create_model(
        "CollisionPayload",
        count=(int, ...),
        __module__="tests.openapi.second",
    )

    async def first_endpoint() -> object:
        return {"value": "first"}

    async def second_endpoint() -> object:
        return {"count": 2}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="first-http",
                path="/api/first",
                methods=("GET",),
                endpoint=first_endpoint,
                name="first",
                response_model=first_payload,
            ),
            RouteDefinitionV2(
                owner_entry_id="second-http",
                path="/api/second",
                methods=("GET",),
                endpoint=second_endpoint,
                name="second",
                response_model=second_payload,
            ),
        )
    )
    descriptor = PluginGenerationDescriptorV2(
        profile_id="openapi-collision",
        generation=1,
        digest="0" * 64,
    )

    components = table.openapi_snapshot(descriptor).schema["components"]["schemas"]
    assert "CollisionPayload" not in components
    assert {
        "tests__openapi__first__CollisionPayload",
        "tests__openapi__second__CollisionPayload",
    } <= components.keys()


@pytest.mark.unit
async def test_route_table_stages_without_visibility_until_atomic_activation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()

    staged = registry.stage(distribution.descriptor, _table("one"))

    assert registry.current is None
    assert registry.resolve(distribution.descriptor) is staged

    registry.activate(staged)
    assert registry.current is staged
    assert registry.current.openapi.descriptor == distribution.descriptor
    await host.close()


@pytest.mark.unit
async def test_dispatch_and_openapi_are_pinned_to_the_same_generation() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    registry = RouteTableRegistryV2()
    first_distribution = host.current_distribution
    assert first_distribution is not None
    first_publication = await registry.publish(first_distribution.descriptor, _table("one"))
    dispatcher = GenerationRouteDispatcherV2(registry)

    async with pin_operation_context_v2(
        host,
        operation_id="old-http-request",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ):
        await host.bootstrap(
            profile_path=_ROOT / "config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=(_ROOT / "config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="route-generation-2",
        )
        second_distribution = host.current_distribution
        assert second_distribution is not None
        second_publication = await registry.publish(second_distribution.descriptor, _table("two"))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dispatcher),
            base_url="http://test",
        ) as client:
            response = await client.get("/api/value")

        assert response.json() == {"generation": "one"}
        assert first_publication.openapi.descriptor.generation == 1
        assert "/api/value" in first_publication.openapi.schema["paths"]
        assert registry.current is second_publication

    async with (
        pin_operation_context_v2(
            host,
            operation_id="new-http-request",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=dispatcher),
            base_url="http://test",
        ) as client,
    ):
        response = await client.get("/api/value")

    assert response.json() == {"generation": "two"}
    assert second_publication.openapi.descriptor.generation == 2
    await host.close()
