import pytest
from fastapi import status
from httpx import AsyncClient

from src.infrastructure.adapters.primary.web.main import create_app
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)

app = create_app()


@pytest.fixture(autouse=True)
async def _memories_v2_runtime(test_app):
    async def graph_runtime_factory():
        return test_app.state.graph_service

    await initialize_plugin_runtime_v2(
        test_app,
        graph_runtime_factory=graph_runtime_factory,
    )
    assert "memories" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


@pytest.mark.asyncio
async def test_extract_entities_with_content(authenticated_async_client):
    client: AsyncClient = authenticated_async_client
    resp = await client.post(
        "/api/v1/memories/extract-entities",
        json={"content": "Alice met Bob in Paris"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "entities" in data
    assert isinstance(data["entities"], list)


@pytest.mark.asyncio
async def test_extract_relationships_with_content(authenticated_async_client):
    client: AsyncClient = authenticated_async_client
    resp = await client.post(
        "/api/v1/memories/extract-relationships",
        json={"content": "Alice met Bob in Paris"},
    )
    assert resp.status_code == status.HTTP_200_OK
    data = resp.json()
    assert "relationships" in data
    assert isinstance(data["relationships"], list)
