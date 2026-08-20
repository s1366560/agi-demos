"""Application lifecycle tests for the protocol v2 runtime."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    plugin_runtime_host_v2_from_scope,
    shutdown_plugin_runtime_v2,
)


@pytest.mark.unit
async def test_initialize_and_shutdown_plugin_runtime_v2() -> None:
    app = FastAPI()

    host = await initialize_plugin_runtime_v2(app)

    assert plugin_runtime_host_v2_from_scope({"app": app}) is host
    assert host.manager.current is not None
    route_registry = app.state.platform_plugin_route_registry_v2
    route_graph = app.state.platform_plugin_route_graph_v2
    assert route_registry.current is not None
    assert route_registry.current.descriptor == host.manager.current.descriptor
    assert len(route_graph.mounted_row_ids) == 71
    assert len(route_graph.route_signatures) > 72
    assert route_registry.current.openapi.descriptor == host.manager.current.descriptor
    await shutdown_plugin_runtime_v2(app)
    assert app.state.platform_plugin_runtime_v2 is None
    assert host.manager.current is None
    assert app.state.platform_plugin_route_registry_v2 is None
    assert app.state.platform_plugin_route_graph_v2 is None


@pytest.mark.unit
def test_scope_resolution_fails_before_runtime_startup() -> None:
    app = FastAPI()

    with pytest.raises(RuntimeError, match="not initialized"):
        plugin_runtime_host_v2_from_scope({"app": app})
