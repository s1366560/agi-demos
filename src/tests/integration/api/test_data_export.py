from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from fastapi import status

from src.domain.model.graph.dtos import GraphExportDTO
from src.infrastructure.adapters.primary.web.dependencies import get_graph_store
from src.infrastructure.adapters.primary.web.dependencies.auth_dependencies import (
    verify_api_key_dependency,
)
from src.infrastructure.adapters.secondary.persistence.models import APIKey


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
def mock_graphiti_service():
    service = AsyncMock()
    service.data_export = AsyncMock()
    service.count_stats = AsyncMock()
    service.count_episodes_by_age = AsyncMock()
    service.delete_episodes_by_age = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_export_data(mock_api_key_dependency, mock_graphiti_service, test_app, async_client):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graph_store] = lambda: mock_graphiti_service

    mock_props = {"uuid": "123", "content": "test"}
    mock_graphiti_service.data_export.return_value = GraphExportDTO(
        exported_at="2026-08-05T00:00:00+00:00",
        tenant_id=None,
        project_id=None,
        episodes=[mock_props],
    )

    response = await async_client.post(
        "/api/v1/data/export",
        json={
            "include_episodes": True,
            "include_entities": False,
            "include_relationships": False,
            "include_communities": False,
        },
    )

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert "episodes" in data
    assert len(data["episodes"]) == 1
    assert data["episodes"][0] == mock_props

    mock_graphiti_service.data_export.assert_awaited_once_with(
        tenant_id=None,
        project_id=None,
        include_episodes=True,
        include_entities=False,
        include_relationships=False,
        include_communities=False,
    )

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_get_stats(mock_api_key_dependency, mock_graphiti_service, test_app, async_client):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graph_store] = lambda: mock_graphiti_service

    mock_graphiti_service.count_stats.return_value = {
        "entities": 5,
        "episodes": 5,
        "communities": 5,
        "relationships": 5,
        "total_nodes": 15,
    }
    response = await async_client.get("/api/v1/data/stats")

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    # Since we use the same mock for all 4 queries (entities, episodes, communities, rels), all counts will be 5
    assert data["entities"] == 5
    assert data["episodes"] == 5
    assert data["communities"] == 5
    assert data["relationships"] == 5
    assert data["total_nodes"] == 15  # 5+5+5

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_cleanup_dry_run(
    mock_api_key_dependency, mock_graphiti_service, test_db, async_client, test_app, test_user
):
    # Setup overrides on the test app
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graph_store] = lambda: mock_graphiti_service

    # User is already created by test_user fixture
    # Do NOT create user manually here

    mock_graphiti_service.count_episodes_by_age.return_value = 5

    response = await async_client.post("/api/v1/data/cleanup", json={"dry_run": True})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["dry_run"] is True
    assert data["would_delete"] == 5

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_cleanup_execute(
    mock_api_key_dependency, mock_graphiti_service, test_db, async_client, test_app, test_user
):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graph_store] = lambda: mock_graphiti_service

    # User is already created by test_user fixture

    mock_graphiti_service.delete_episodes_by_age.return_value = 5

    response = await async_client.post("/api/v1/data/cleanup", params={"dry_run": False})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["dry_run"] is False
    assert data["deleted"] == 5

    test_app.dependency_overrides = {}
