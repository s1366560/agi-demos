"""Unit tests for episodes router."""

from datetime import datetime
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import status


@pytest.mark.unit
class TestEpisodesRouter:
    """Test cases for episodes router endpoints."""

    @pytest.mark.asyncio
    async def test_create_episode_success(self, client, mock_graphiti_client, sample_episode_data):
        """Test successful episode creation."""
        from unittest.mock import Mock
        from uuid import uuid4

        # Mock response - return a proper result object
        mock_episode = Mock()
        mock_episode.uuid = str(uuid4())
        mock_result = Mock()
        mock_result.episode = mock_episode
        mock_graphiti_client.add_episode = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/episodes/",
            json=sample_episode_data,
        )

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        data = response.json()
        assert data["status"] == "processing"
        assert data["message"] == "Episode queued for ingestion"
        assert "id" in data
        assert "created_at" in data

    @pytest.mark.asyncio
    async def test_create_episode_auto_generate_name(
        self, client, mock_graphiti_client, sample_episode_data
    ):
        """Test episode creation with auto-generated name."""
        from unittest.mock import Mock
        from uuid import uuid4

        # Remove name from data
        episode_data = sample_episode_data.copy()
        del episode_data["name"]

        # Mock response - return a proper result object
        mock_episode = Mock()
        mock_episode.uuid = str(uuid4())
        mock_result = Mock()
        mock_result.episode = mock_episode
        mock_graphiti_client.add_episode = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post("/api/v1/episodes/", json=episode_data)

        # Assert
        assert response.status_code == status.HTTP_202_ACCEPTED
        mock_graphiti_client.add_episode.assert_called_once()
        # Name should be auto-generated from content
        call_args = mock_graphiti_client.add_episode.call_args
        assert call_args is not None

    @pytest.mark.asyncio
    async def test_create_episode_failure(self, client, mock_graphiti_client, sample_episode_data):
        """Test episode creation failure handling."""
        # Mock failure
        mock_graphiti_client.add_episode = AsyncMock(side_effect=Exception("Database error"))

        # Make request
        response = client.post("/api/v1/episodes/", json=sample_episode_data)

        # Assert
        assert response.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
        assert "Failed to create episode" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_get_episode_success(self, client, mock_graphiti_client):
        """Test successful episode retrieval."""
        # Mock response
        mock_records = [
            {
                "props": {
                    "uuid": "ep_123",
                    "name": "Test Episode",
                    "content": "Test content",
                    "source_description": "text",
                    "created_at": datetime.utcnow().isoformat(),
                    "valid_at": datetime.utcnow().isoformat(),
                    "tenant_id": "tenant_123",
                    "project_id": "proj_123",
                    "user_id": "user_123",
                    "status": "completed",
                }
            }
        ]

        mock_result = Mock()
        mock_result.records = mock_records
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.get("/api/v1/episodes/by-name/Test Episode")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["uuid"] == "ep_123"
        assert data["name"] == "Test Episode"
        assert data["content"] == "Test content"
        assert data["status"] == "completed"

    @pytest.mark.asyncio
    async def test_get_episode_not_found(self, client, mock_graphiti_client):
        """Test episode retrieval when episode not found."""
        # Mock empty response
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.get("/api/v1/episodes/by-name/Nonexistent Episode")

        # Assert
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Episode not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_list_episodes_success(self, client, mock_graphiti_client):
        """Test successful episode listing."""
        # Mock count response
        count_record = Mock()
        count_record.__getitem__ = lambda self, key: 10  # total
        count_result = Mock()
        count_result.records = [count_record]

        # Mock list response
        list_records = []
        for i in range(5):
            props = {
                "uuid": f"ep_{i}",
                "name": f"Episode {i}",
                "content": f"Content {i}",
                "created_at": datetime.utcnow().isoformat(),
                "status": "completed",
            }
            record = Mock()
            record.__getitem__ = lambda self, key: props
            list_records.append(record)

        list_result = Mock()
        list_result.records = list_records

        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[count_result, list_result]
        )

        # Make request
        response = client.get("/api/v1/episodes/?limit=5&offset=0")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "episodes" in data
        assert data["total"] == 10
        assert len(data["episodes"]) == 5
        assert data["limit"] == 5
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_episodes_with_filters(self, client, mock_graphiti_client):
        """Test episode listing with filters."""
        # Mock count response
        count_record = Mock()
        count_record.__getitem__ = lambda self, key: 5  # total
        count_result = Mock()
        count_result.records = [count_record]

        # Mock list response (empty)
        list_result = Mock()
        list_result.records = []

        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[count_result, list_result]
        )

        # Make request with filters
        response = client.get("/api/v1/episodes/?tenant_id=tenant_123&project_id=proj_123&limit=10")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        # Verify query was called with filters
        assert mock_graphiti_client.driver.execute_query.call_count == 2

    @pytest.mark.asyncio
    async def test_delete_episode_success(self, client, mock_graphiti_client):
        """Test successful episode deletion."""
        # Mock response - need subscriptable record
        record = Mock()
        record.__getitem__ = lambda self, key: 1  # deleted count
        mock_result = Mock()
        mock_result.records = [record]
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.delete("/api/v1/episodes/by-name/Test Episode")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "success"
        assert "deleted successfully" in data["message"]

    @pytest.mark.asyncio
    async def test_delete_episode_not_found(self, client, mock_graphiti_client):
        """Test episode deletion when episode not found."""
        # Mock response - no episodes deleted
        record = Mock()
        record.__getitem__ = lambda self, key: 0  # deleted count
        mock_result = Mock()
        mock_result.records = [record]
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.delete("/api/v1/episodes/by-name/Nonexistent Episode")

        # Assert
        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert "Episode not found" in response.json()["detail"]

    @pytest.mark.asyncio
    async def test_health_check_success(self, authenticated_client, mock_graphiti_client):
        """Test health check endpoint."""
        # Mock response - execute_query needs to return a result with records()
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = authenticated_client.get("/api/v1/episodes/health")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_health_check_failure(self, authenticated_client, mock_graphiti_client):
        """Test health check when service is unhealthy."""
        # Mock failure
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=Exception("Connection error")
        )

        # Make request
        response = authenticated_client.get("/api/v1/episodes/health")

        # Assert
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.unit
class TestEpisodesRouterIntegration:
    """Integration tests for episodes router with mocked dependencies."""

    @pytest.mark.asyncio
    async def test_episode_workflow(self, client, mock_graphiti_client, sample_episode_data):
        """Test complete episode workflow: create -> get -> list -> delete."""
        from uuid import uuid4

        # 1. Create episode - return proper result object
        mock_episode = Mock()
        mock_episode.uuid = str(uuid4())
        mock_result = Mock()
        mock_result.episode = mock_episode
        mock_graphiti_client.add_episode = AsyncMock(return_value=mock_result)

        create_response = client.post("/api/v1/episodes/", json=sample_episode_data)
        assert create_response.status_code == status.HTTP_202_ACCEPTED
        episode_id = create_response.json()["id"]

        # 2. Get episode
        mock_records = []
        props = {
            "uuid": episode_id,
            "name": sample_episode_data["name"],
            "content": sample_episode_data["content"],
            "created_at": datetime.utcnow().isoformat(),
            "status": "processing",
        }
        record = Mock()
        record.__getitem__ = lambda self, key: props
        mock_records.append(record)

        mock_result = Mock()
        mock_result.records = mock_records
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        get_response = client.get(f"/api/v1/episodes/by-name/{sample_episode_data['name']}")
        assert get_response.status_code == status.HTTP_200_OK

        # 3. List episodes
        count_record = Mock()
        count_record.__getitem__ = lambda self, key: 1  # total
        count_result = Mock()
        count_result.records = [count_record]

        list_result = Mock()
        list_result.records = mock_records
        mock_graphiti_client.driver.execute_query = AsyncMock(
            side_effect=[count_result, list_result]
        )

        list_response = client.get("/api/v1/episodes/")
        assert list_response.status_code == status.HTTP_200_OK
        assert len(list_response.json()["episodes"]) == 1

        # 4. Delete episode
        delete_record = Mock()
        delete_record.__getitem__ = lambda self, key: 1  # deleted
        delete_result = Mock()
        delete_result.records = [delete_record]
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=delete_result)

        delete_response = client.delete(f"/api/v1/episodes/by-name/{sample_episode_data['name']}")
        assert delete_response.status_code == status.HTTP_200_OK
