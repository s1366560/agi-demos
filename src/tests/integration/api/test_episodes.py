from collections.abc import AsyncIterator
from datetime import UTC, datetime
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import FastAPI, status
from httpx import ASGITransport, AsyncClient

from src.domain.model.memory.episode import Episode, SourceType
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
async def _episodes_v2_runtime(
    test_app: FastAPI,
    mock_graphiti_service: object,
) -> AsyncIterator[None]:
    """Publish the graph test adapter through the production generation."""

    async def graph_runtime_factory() -> object:
        return mock_graphiti_service

    await initialize_plugin_runtime_v2(test_app, graph_runtime_factory=graph_runtime_factory)
    assert "episodes" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
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


@pytest.fixture
def mock_episode_data():
    return {
        "content": "Test Episode Content",
        "source": "web",
        "source_id": "test-source",
        "context": {"key": "value"},
    }


@pytest.mark.asyncio
async def test_create_episode(
    test_app, mock_graphiti_service, mock_api_key_dependency, mock_episode_data
):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency

    created_episode_id = str(uuid4())
    mock_graphiti_service.add_episode = AsyncMock(
        return_value=Episode(
            id=created_episode_id,
            name=mock_episode_data["content"][:50] + "...",
            content=mock_episode_data["content"],
            source_type=SourceType.TEXT,
            valid_at=datetime.now(UTC),
        )
    )

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/episodes/", json=mock_episode_data)

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert data["id"] == created_episode_id
    assert data["status"] == "processing"

    added_episode = mock_graphiti_service.add_episode.call_args.args[0]
    assert isinstance(added_episode, Episode)
    assert added_episode.content == mock_episode_data["content"]

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_health_check(test_app, mock_graphiti_service):
    mock_graphiti_service.health_probe = AsyncMock(return_value=True)

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/episodes/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "healthy"

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_health_check_unhealthy(test_app, mock_graphiti_service):
    mock_graphiti_service.health_probe = AsyncMock(side_effect=Exception("Connection error"))

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/episodes/health")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    test_app.dependency_overrides = {}
