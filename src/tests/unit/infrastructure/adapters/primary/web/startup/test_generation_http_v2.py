"""Stable generation dispatcher and OpenAPI publication tests."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.responses import StreamingResponse
from starlette.routing import Match
from starlette.testclient import TestClient

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.domain.model.plugins.runtime import PluginGenerationDescriptorV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    ApplicationGenerationRouteDispatcherV2,
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    PluginGenerationMiddlewareV2,
    current_generation_v2,
    pin_generation_v2,
    pin_operation_context_v2,
)
from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
from src.infrastructure.plugins.v2.http_routes import (
    RouteDefinitionV2,
    RouteTableRegistryV2,
    RouteTableV2,
)
from src.infrastructure.plugins.v2.runtime_host import PlatformPluginRuntimeHostV2


@pytest.mark.unit
async def test_observability_route_match_uses_current_publication_before_boundary_pin() -> None:
    app = FastAPI()
    mount_generation_http_dispatcher_v2(app)
    dispatcher = next(
        route
        for route in app.router.routes
        if isinstance(route, ApplicationGenerationRouteDispatcherV2)
    )
    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="observability-route",
                path="/api/observed",
                methods=("GET",),
                endpoint=lambda: {"ok": True},
                name="observed",
            ),
        )
    )
    registry = RouteTableRegistryV2()
    await registry.publish(
        PluginGenerationDescriptorV2(
            profile_id="observability",
            generation=1,
            digest="0" * 64,
        ),
        table,
    )
    app.state.platform_plugin_route_registry_v2 = registry

    match, child_scope = dispatcher.matches(
        {
            "type": "http",
            "method": "GET",
            "path": "/api/observed",
            "root_path": "",
        }
    )

    assert match is Match.FULL
    assert child_scope == {"endpoint": dispatcher}


@pytest.mark.unit
async def test_kernel_precedes_dispatcher_and_dispatcher_precedes_legacy_fallback() -> None:
    app = FastAPI()

    @app.get("/kernel")
    async def kernel() -> dict[str, str]:
        return {"source": "kernel"}

    mount_generation_http_dispatcher_v2(app)

    @app.get("/api/value")
    async def legacy() -> dict[str, str]:
        return {"source": "legacy"}

    @app.get("/api/dynamic")
    async def dynamic() -> dict[str, str]:
        return {"source": "dynamic-fallback"}

    async def plugin() -> dict[str, str]:
        return {"source": "generation"}

    table = RouteTableV2(
        (
            RouteDefinitionV2(
                owner_entry_id="plugin-route",
                path="/api/value",
                methods=("GET",),
                endpoint=plugin,
                name="plugin-value",
            ),
        )
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
    publication = await registry.publish(distribution.descriptor, table)
    app.state.platform_plugin_route_registry_v2 = registry

    async with (
        pin_operation_context_v2(
            host,
            operation_id="dispatcher-test",
            scope=ScopeV2(kind=ScopeKindV2.ROOT),
        ),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as client,
    ):
        kernel_response = await client.get("/kernel")
        plugin_response = await client.get("/api/value")
        dynamic_response = await client.get("/api/dynamic")

    assert kernel_response.json() == {"source": "kernel"}
    assert plugin_response.json() == {"source": "generation"}
    assert dynamic_response.json() == {"source": "dynamic-fallback"}
    assert app.openapi() == dict(publication.openapi.schema)
    await host.close()


@pytest.mark.unit
async def test_openapi_uses_the_exact_pinned_generation_after_new_publication() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    first_distribution = host.current_distribution
    assert first_distribution is not None

    def _table(path: str, *, name: str) -> RouteTableV2:
        return RouteTableV2(
            (
                RouteDefinitionV2(
                    owner_entry_id=name,
                    path=path,
                    methods=("GET",),
                    endpoint=lambda: {"source": name},
                    name=name,
                ),
            )
        )

    registry = RouteTableRegistryV2()
    await registry.publish(
        first_distribution.descriptor,
        _table("/api/v1/generation-one", name="generation-one"),
    )
    app = FastAPI()
    app.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(app)

    async with pin_generation_v2(host):
        await host.bootstrap(
            profile_path="config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="openapi-generation-2",
        )
        second_distribution = host.current_distribution
        assert second_distribution is not None
        await registry.publish(
            second_distribution.descriptor,
            _table("/api/v1/generation-two", name="generation-two"),
        )

        pinned_paths = set(app.openapi()["paths"])

    current_paths = set(app.openapi()["paths"])
    assert "/api/v1/generation-one" in pinned_paths
    assert "/api/v1/generation-two" not in pinned_paths
    assert "/api/v1/generation-two" in current_paths
    assert "/api/v1/generation-one" not in current_paths
    await host.close()


@pytest.mark.unit
async def test_streaming_request_keeps_old_route_generation_until_final_body() -> None:
    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=1,
        version=1,
    )
    first_chunk_sent = asyncio.Event()
    finish_first_response = asyncio.Event()

    async def first_endpoint() -> StreamingResponse:
        async def body():
            yield f"{current_generation_v2().generation}:start".encode()
            first_chunk_sent.set()
            await finish_first_response.wait()
            yield f":{current_generation_v2().generation}".encode()

        return StreamingResponse(body())

    async def second_endpoint() -> dict[str, int]:
        return {"generation": current_generation_v2().generation}

    def table(endpoint, *, name: str) -> RouteTableV2:
        return RouteTableV2(
            (
                RouteDefinitionV2(
                    owner_entry_id="plugin-route",
                    path="/api/stream",
                    methods=("GET",),
                    endpoint=endpoint,
                    name=name,
                ),
            )
        )

    first_distribution = host.current_distribution
    assert first_distribution is not None
    registry = RouteTableRegistryV2()
    await registry.publish(
        first_distribution.descriptor,
        table(first_endpoint, name="stream-first"),
    )
    outer = FastAPI()
    outer.state.platform_plugin_route_registry_v2 = registry
    mount_generation_http_dispatcher_v2(outer)
    application = PluginGenerationMiddlewareV2(outer, host_provider=lambda _scope: host)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=application),
        base_url="http://test",
    ) as client:
        first_request = asyncio.create_task(client.get("/api/stream"))
        await first_chunk_sent.wait()
        await host.bootstrap(
            profile_path="config/plugin-profiles/memstack-default.v2.yaml",
            manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
            generation=2,
            version=2,
            nonce="stream-generation-2",
        )
        second_distribution = host.current_distribution
        assert second_distribution is not None
        await registry.publish(
            second_distribution.descriptor,
            table(second_endpoint, name="stream-second"),
        )
        finish_first_response.set()

        first_response = await first_request
        second_response = await client.get("/api/stream")

    assert first_response.text == "1:start:1"
    assert second_response.json() == {"generation": 2}
    await host.close()


@pytest.mark.unit
async def test_websocket_connection_keeps_its_pinned_route_generation() -> None:
    outer = FastAPI()
    mount_generation_http_dispatcher_v2(outer)
    first_routes = FastAPI()

    @first_routes.websocket("/api/v1/agent/ws")
    async def first_websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json(
            {
                "route_generation": 7,
                "pinned_generation": current_generation_v2().generation,
            }
        )
        _ = await websocket.receive_text()
        await websocket.send_json({"pinned_after_reload": current_generation_v2().generation})
        await websocket.close()

    host = PlatformPluginRuntimeHostV2(builtin_runtime_definitions_v2())
    await host.bootstrap(
        profile_path="config/plugin-profiles/memstack-default.v2.yaml",
        manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
        generation=7,
        version=7,
    )
    distribution = host.current_distribution
    assert distribution is not None
    registry = RouteTableRegistryV2()
    await registry.publish(
        distribution.descriptor,
        RouteTableV2.from_fastapi_graph(first_routes),
    )
    outer.state.platform_plugin_route_registry_v2 = registry
    application = PluginGenerationMiddlewareV2(outer, host_provider=lambda _scope: host)

    with TestClient(application) as client:
        with client.websocket_connect("/api/v1/agent/ws") as websocket:
            assert websocket.receive_json() == {
                "route_generation": 7,
                "pinned_generation": 7,
            }

            await host.bootstrap(
                profile_path="config/plugin-profiles/memstack-default.v2.yaml",
                manifest_paths=("config/plugin-manifests-v2/memstack-runtime-kernel.v2.json",),
                generation=8,
                version=8,
                nonce="websocket-generation-8",
            )
            second_distribution = host.current_distribution
            assert second_distribution is not None
            second_routes = FastAPI()

            @second_routes.websocket("/api/v1/agent/ws")
            async def second_websocket_endpoint(second_websocket: WebSocket) -> None:
                await second_websocket.accept()
                await second_websocket.send_json(
                    {
                        "route_generation": 8,
                        "pinned_generation": current_generation_v2().generation,
                    }
                )
                await second_websocket.close()

            await registry.publish(
                second_distribution.descriptor,
                RouteTableV2.from_fastapi_graph(second_routes),
            )
            websocket.send_text("continue")
            assert websocket.receive_json() == {"pinned_after_reload": 7}

        with client.websocket_connect("/api/v1/agent/ws") as websocket:
            assert websocket.receive_json() == {
                "route_generation": 8,
                "pinned_generation": 8,
            }

    await host.close()
