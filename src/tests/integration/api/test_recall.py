from collections.abc import AsyncIterator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    verify_api_key_dependency,
)
from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _recall_v2_runtime(
    test_app: FastAPI,
    mock_graphiti_service: object,
) -> AsyncIterator[None]:
    """Publish the graph test adapter through the production generation."""

    async def graph_runtime_factory() -> object:
        return mock_graphiti_service

    await initialize_plugin_runtime_v2(test_app, graph_runtime_factory=graph_runtime_factory)
    assert "recall" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
    try:
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


@pytest.fixture
def mock_api_key_dependency(test_user):
    return APIKey(
        id=str(uuid4()),
        key_hash="hash",
        name="test-key",
        user_id=test_user.id,
        permissions=["read", "write"],
    )


@pytest.mark.asyncio
async def test_short_term_recall(test_app, mock_graphiti_service, mock_api_key_dependency):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency

    mock_graphiti_service.recall_recent_episodes = AsyncMock(
        return_value=[{"uuid": "episode-1", "name": "mem1", "content": "mem1"}]
    )

    payload = {"window_minutes": 60, "limit": 10, "tenant_id": "tenant-1"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/recall/short", json=payload)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert "results" in data and isinstance(data["results"], list)
    assert data["total"] == 1
    assert data["window_minutes"] == 60
    assert data["results"][0]["uuid"] == "episode-1"
    assert data["results"][0]["content"] == "mem1"
    mock_graphiti_service.recall_recent_episodes.assert_awaited_once()
    arguments = mock_graphiti_service.recall_recent_episodes.call_args.kwargs
    assert arguments["limit"] == 10
    assert arguments["tenant_id"] == "tenant-1"
    assert arguments["project_id"] is None
    assert arguments["project_ids"] is None

    test_app.dependency_overrides = {}
