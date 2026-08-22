import pytest
from fastapi import status

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)


@pytest.fixture(autouse=True)
async def _projects_v2_runtime(test_app):
    """Exercise the migrated projects row through the production generation dispatcher."""
    await initialize_plugin_runtime_v2(test_app)
    assert "projects" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


@pytest.mark.asyncio
async def test_create_project_invalid_data(authenticated_async_client):
    # Missing required fields
    response = await authenticated_async_client.post("/api/v1/projects/", json={})

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
