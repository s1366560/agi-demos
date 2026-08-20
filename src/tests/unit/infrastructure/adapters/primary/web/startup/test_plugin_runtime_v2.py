"""Application lifecycle tests for the protocol v2 runtime."""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.adapters.primary.web.startup.generation_http_v2 import (
    mount_generation_http_dispatcher_v2,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    plugin_runtime_host_v2_from_scope,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.plugins.v2.boundary import PluginGenerationMiddlewareV2
from src.infrastructure.plugins.v2.http_routes import RouteDefinitionV2, RouteTableBuilderV2
from src.infrastructure.plugins.v2.legacy_http_route_bridge import (
    configured_legacy_http_routes_v2,
)
from src.infrastructure.plugins.v2.route_effects import ROUTE_TABLE_BUILDER_SERVICE_V2
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error


@pytest.mark.unit
async def test_initialize_and_shutdown_plugin_runtime_v2() -> None:
    app = FastAPI()

    host = await initialize_plugin_runtime_v2(app)

    assert plugin_runtime_host_v2_from_scope({"app": app}) is host
    assert host.manager.current is not None
    route_registry = app.state.platform_plugin_route_registry_v2
    route_graph = app.state.platform_plugin_route_graph_v2
    assert app.state.platform_plugin_http_route_publication_v2 is not None
    assert route_registry.current is not None
    assert route_registry.current.descriptor == host.manager.current.descriptor
    assert len(route_graph.mounted_row_ids) == 71
    assert len(route_graph.route_signatures) > 72
    assert route_registry.current.openapi.descriptor == host.manager.current.descriptor
    route_builder = host.manager.current.resolve(
        ROUTE_TABLE_BUILDER_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    assert isinstance(route_builder, RouteTableBuilderV2)
    with pytest.raises(RuntimeV2Error) as error:
        route_builder.contribute(
            RouteDefinitionV2(
                owner_entry_id="late-route",
                path="/api/v2/late",
                methods=("GET",),
                endpoint=lambda: {"ok": True},
                name="late-route",
            )
        )
    assert error.value.code == "route_table_frozen"
    await shutdown_plugin_runtime_v2(app)
    assert app.state.platform_plugin_runtime_v2 is None
    assert host.manager.current is None
    assert app.state.platform_plugin_route_registry_v2 is None
    assert app.state.platform_plugin_route_graph_v2 is None
    assert app.state.platform_plugin_http_route_publication_v2 is None


@pytest.mark.unit
def test_scope_resolution_fails_before_runtime_startup() -> None:
    app = FastAPI()

    with pytest.raises(RuntimeError, match="not initialized"):
        plugin_runtime_host_v2_from_scope({"app": app})


def _desired_route(*, path: str = "/plugin-startup/{tenant_id}/hello") -> SimpleNamespace:
    return SimpleNamespace(
        plugin_id="startup-plugin",
        method="GET",
        path=path,
        permission="plugin.startup.read",
        authorization_mode="tenant_member",
        enabled=True,
    )


def _route_inventory(
    *,
    path: str = "/plugin-startup/{tenant_id}/hello",
) -> dict[str, list[SimpleNamespace]]:
    async def handler(tenant_id: str) -> dict[str, str]:
        return {"tenant_id": tenant_id, "source": "generation-one"}

    return {
        "startup-plugin": [
            SimpleNamespace(
                plugin_name="startup-plugin",
                method="GET",
                path=path,
                handler=handler,
                tags=("Startup",),
            )
        ]
    }


async def _allow_route() -> None:
    return None


@pytest.mark.unit
async def test_generation_one_projects_desired_routes_without_outer_mount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/plugin-startup/{tenant_id}/hello"
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        _route_inventory,
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_authorization",
        lambda _row: _allow_route,
    )
    app = FastAPI()
    app.add_middleware(
        PluginGenerationMiddlewareV2,
        host_provider=plugin_runtime_host_v2_from_scope,
    )
    mount_generation_http_dispatcher_v2(app)

    host = await initialize_plugin_runtime_v2(
        app,
        desired_http_route_rows=(_desired_route(),),
    )

    distribution = host.current_distribution
    assert distribution is not None
    assert distribution.descriptor.generation == 1
    assert configured_legacy_http_routes_v2(distribution.snapshot.entries)[0].path == path
    assert path not in {getattr(route, "path", None) for route in app.router.routes}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/plugin-startup/tenant-1/hello")
    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant-1", "source": "generation-one"}
    await host.close()


@pytest.mark.unit
async def test_generation_one_fails_closed_when_desired_handler_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        dict,
    )
    app = FastAPI()

    with pytest.raises(RuntimeError, match="handler is not owned"):
        await initialize_plugin_runtime_v2(app, desired_http_route_rows=(_desired_route(),))

    assert not hasattr(app.state, "platform_plugin_runtime_v2")


@pytest.mark.unit
async def test_generation_one_fails_closed_when_desired_path_is_unsafe() -> None:
    app = FastAPI()

    with pytest.raises(ValueError, match="unsafe legacy HTTP route definition"):
        await initialize_plugin_runtime_v2(
            app,
            desired_http_route_rows=(_desired_route(path="not-an-absolute-path"),),
        )

    assert not hasattr(app.state, "platform_plugin_runtime_v2")


@pytest.mark.unit
async def test_generation_one_fails_closed_on_builtin_route_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = "/api/v1/tenants/{tenant_id}"
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_inventory",
        lambda: _route_inventory(path=path),
    )
    monkeypatch.setattr(
        "src.infrastructure.plugins.v2.legacy_http_route_bridge._legacy_authorization",
        lambda _row: _allow_route,
    )
    app = FastAPI()

    with pytest.raises(RuntimeV2Error, match="conflicts with private graph"):
        await initialize_plugin_runtime_v2(
            app,
            desired_http_route_rows=(_desired_route(path=path),),
        )

    assert not hasattr(app.state, "platform_plugin_runtime_v2")
