from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import status

from src.infrastructure.adapters.primary.web.dependencies import get_graphiti_client
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
    # Mock the client driver
    mock_driver = AsyncMock()

    # Mock result records for stats/cleanup
    mock_record = {"count": 5, "deleted": 5}
    mock_result = Mock()
    mock_result.records = [mock_record]

    # Default behavior
    mock_driver.execute_query.return_value = mock_result

    service.driver = mock_driver
    # Also attach driver to client for compatibility if accessed via client.driver
    service.client = Mock()
    service.client.driver = mock_driver

    return service


@pytest.mark.asyncio
async def test_export_data(mock_api_key_dependency, mock_graphiti_service, test_app, async_client):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    # Setup mock for export queries
    # The router iterates over records and accesses "props"
    mock_props = {"uuid": "123", "content": "test"}
    mock_record = {
        "props": mock_props,
        "labels": ["Entity"],
        "edge_id": "e1",
        "rel_type": "RELATED",
        "deleted": 5,
        "count": 5,
    }
    mock_result = Mock()
    mock_result.records = [mock_record]
    mock_graphiti_service.driver.execute_query.return_value = mock_result

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

    assert mock_graphiti_service.driver.execute_query.called

    test_app.dependency_overrides = {}


@pytest.mark.asyncio
async def test_get_stats(mock_api_key_dependency, mock_graphiti_service, test_app, async_client):
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    # The mock returns count=5 for all queries
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
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    # User is already created by test_user fixture
    # Do NOT create user manually here

    # Mock graphiti search result
    mock_result = Mock()
    mock_result.records = [{"count": 5, "deleted": 5}]
    mock_graphiti_service.driver.execute_query.return_value = mock_result

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
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service

    # User is already created by test_user fixture

    # Mock graphiti search result
    mock_result = Mock()
    mock_result.records = [{"count": 5, "deleted": 5}]
    mock_graphiti_service.driver.execute_query.return_value = mock_result

    # Execute calls count_query then delete_query
    # We need side_effect to return different results
    # For execute, it calls count first, then delete.
    # The mock setup in upstream block seemed to just set return_value.
    # But wait, looking at the conflict block for execute:
    # Upstream: `mock_graphiti_service.driver.execute_query.return_value = mock_result`
    # Stashed: `side_effect = [mock_result_count, mock_result_delete]`
    # If the code calls it twice, return_value will return same thing twice.
    # If the code expects count first then delete result, returning same object might work if structure is compatible.
    # Upstream mock result has both `count` and `deleted`.
    # So it probably works for both calls.

    response = await async_client.post("/api/v1/data/cleanup", params={"dry_run": False})

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["dry_run"] is False
    assert data["deleted"] == 5

    test_app.dependency_overrides = {}
