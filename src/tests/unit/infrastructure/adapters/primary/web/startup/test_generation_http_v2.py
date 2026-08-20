"""Stable generation dispatcher and OpenAPI publication tests."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, WebSocket
from starlette.testclient import TestClient

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.plugins.v2.boundary import pin_operation_context_v2
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

    assert kernel_response.json() == {"source": "kernel"}
    assert plugin_response.json() == {"source": "generation"}
    assert app.openapi() == dict(publication.openapi.schema)
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
