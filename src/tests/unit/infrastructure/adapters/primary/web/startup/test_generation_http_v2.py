"""Stable generation dispatcher and OpenAPI publication tests."""

from __future__ import annotations

import asyncio

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.responses import StreamingResponse
from starlette.testclient import TestClient

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2.boundary import (
    PluginGenerationMiddlewareV2,
    current_generation_v2,
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
async def test_websocket_handshake_routes_without_connection_generation_pin() -> None:
    outer = FastAPI()
    mount_generation_http_dispatcher_v2(outer)
    private = FastAPI()

    @private.websocket("/api/v1/agent/ws")
    async def websocket_endpoint(websocket: WebSocket) -> None:
        await websocket.accept()
        await websocket.send_json({"route_generation": 7})
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
    await registry.publish(distribution.descriptor, RouteTableV2.from_fastapi_graph(private))
    outer.state.platform_plugin_route_registry_v2 = registry

    with TestClient(outer) as client, client.websocket_connect("/api/v1/agent/ws") as websocket:
        assert websocket.receive_json() == {"route_generation": 7}

    await host.close()
