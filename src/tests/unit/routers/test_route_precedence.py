"""Regression tests for static API routes that overlap dynamic resource paths."""

import pytest

from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)


@pytest.mark.unit
async def test_workspace_routing_policy_precedes_dynamic_provider_route() -> None:
    app = create_app()
    await initialize_plugin_runtime_v2(app)
    try:
        publication = app.state.platform_plugin_route_registry_v2.current
        assert publication is not None
        paths = [route.path for route in publication.table.definitions]

        assert paths.index("/api/v1/llm-providers/routing-policy") < paths.index(
            "/api/v1/llm-providers/{provider_id}"
        )
    finally:
        await shutdown_plugin_runtime_v2(app)
