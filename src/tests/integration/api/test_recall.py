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


@pytest.mark.asyncio
async def test_short_term_recall(test_app, mock_graphiti_service, mock_api_key_dependency):
    test_app.dependency_overrides[get_graphiti_client] = lambda: mock_graphiti_service
    test_app.dependency_overrides[verify_api_key_dependency] = lambda: mock_api_key_dependency

    # Mock driver execute_query for recall
    mock_graphiti_service.driver = Mock()
    mock_graphiti_service.driver.execute_query = AsyncMock(
        return_value=Mock(records=[{"props": {"name": "mem1", "content": "mem1"}}])
    )

    payload = {"window_minutes": 60, "limit": 10, "tenant_id": "tenant-1"}

    async with AsyncClient(transport=ASGITransport(app=test_app), base_url="http://test") as ac:
        response = await ac.post("/api/v1/recall/short", json=payload)

    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert response.status_code == status.HTTP_200_OK
    assert "results" in data and isinstance(data["results"], list)
    assert data["total"] >= 0

    test_app.dependency_overrides = {}
