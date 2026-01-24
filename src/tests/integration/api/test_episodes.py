from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import status
from httpx import ASGITransport, AsyncClient

from src.infrastructure.adapters.primary.web.dependencies import get_graphiti_client
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    verify_api_key_dependency,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey

# NOTE: These tests use production app instead of test_app fixture
# They need refactoring to use test_app for proper database isolation
pytestmark = pytest.mark.integration


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
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency

    # Mock add_episode returns result.episode.uuid
    mock_result = Mock()
    mock_result.episode = Mock(uuid=str(uuid4()))
    mock_graphiti_service.add_episode = AsyncMock(return_value=mock_result)
    # Mock driver for health queries
    mock_graphiti_service.driver = Mock()
    mock_graphiti_service.driver.execute_query = AsyncMock(return_value=Mock(records=[]))

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/episodes/", json=mock_episode_data)

    assert response.status_code == status.HTTP_202_ACCEPTED
    data = response.json()
    assert data["id"] == mock_result.episode.uuid
    assert data["status"] == "processing"

    assert mock_graphiti_service.add_episode.called

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_health_check(test_app, mock_graphiti_service):
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    mock_graphiti_service.driver = Mock()
    mock_graphiti_service.driver.execute_query = AsyncMock(return_value=Mock(records=[{"test": 1}]))

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/episodes/health")

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "healthy"

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_health_check_unhealthy(test_app, mock_graphiti_service):
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    mock_graphiti_service.driver = Mock()
    mock_graphiti_service.driver.execute_query = AsyncMock(
        side_effect=Exception("Connection error")
    )

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.get("/api/v1/episodes/health")

    assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE

    test_app.dependency_overrides = {}
