"""Unit tests for data_export, maintenance, and tasks routers."""

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import status


@pytest.mark.unit
class TestDataExportRouter:
    """Test cases for data_export router endpoints."""

    @pytest.mark.asyncio
    async def test_export_data_all(self, client, mock_graphiti_client):
        """Test exporting all data types."""
        # Mock responses
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/data/export",
            json={
                "include_episodes": True,
                "include_entities": True,
                "include_relationships": True,
                "include_communities": True,
            },
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "exported_at" in data
        assert "episodes" in data
        assert "entities" in data
        assert "relationships" in data
        assert "communities" in data

    @pytest.mark.asyncio
    async def test_export_data_filter_by_tenant(self, client, mock_graphiti_client):
        """Test exporting data with tenant filter."""
        # Mock response
        mock_result = Mock()
        mock_result.records = []
        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/data/export",
            json={"tenant_id": "tenant_123", "include_episodes": True},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["tenant_id"] == "tenant_123"

    @pytest.mark.asyncio
    async def test_get_graph_stats(self, client, mock_graphiti_client):
        """Test getting graph statistics."""

        # Mock count responses
        def mock_query(query, **kwargs):
            result = Mock()
            if "Entity" in query:
                # records[0]["count"] needs to work
                record = Mock()
                record.__getitem__ = lambda self, key: 100
                result.records = [record]
            elif "Episodic" in query:
                record = Mock()
                record.__getitem__ = lambda self, key: 50
                result.records = [record]
            elif "Community" in query:
                record = Mock()
                record.__getitem__ = lambda self, key: 10
                result.records = [record]
            else:
                record = Mock()
                record.__getitem__ = lambda self, key: 200
                result.records = [record]
            return result

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(side_effect=mock_query)

        # Make request
        response = client.get("/api/v1/data/stats")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "entities" in data
        assert "episodes" in data
        assert "communities" in data
        assert "relationships" in data
        assert "total_nodes" in data

    @pytest.mark.asyncio
    async def test_cleanup_data_dry_run(self, client, mock_graphiti_client):
        """Test data cleanup in dry run mode."""
        # Mock count response - use dict for record to support subscript access
        count_result = Mock()
        count_result.records = [{"count": 25}]

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(return_value=count_result)

        # Make request
        response = client.post(
            "/api/v1/data/cleanup?dry_run=true&older_than_days=90",
            json={},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True
        assert data["would_delete"] == 25
        assert "cutoff_date" in data

    @pytest.mark.asyncio
    async def test_cleanup_data_execute(self, client, mock_graphiti_client):
        """Test actual data cleanup execution."""
        # Mock responses - use dicts for records to support subscript access
        responses = [
            Mock(records=[{"count": 10}]),  # Count query
            Mock(records=[{"deleted": 10}]),  # Delete query
        ]

        mock_graphiti_client.driver = Mock()
        mock_graphiti_client.driver.execute_query = AsyncMock(side_effect=responses)

        # Make request
        response = client.post(
            "/api/v1/data/cleanup?dry_run=false&older_than_days=30",
            json={},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is False
        assert data["deleted"] == 10


@pytest.mark.unit
class TestMaintenanceRouter:
    """Test cases for maintenance router endpoints."""

    @pytest.mark.asyncio
    async def test_deduplicate_entities_dry_run(self, client, mock_graphiti_client):
        """Test entity deduplication in dry run mode."""
        # Mock response with duplicates
        mock_records = [
            {
                "name": "Duplicate Entity",
                "entities": [{"uuid": "ent_1"}, {"uuid": "ent_2"}],
            }
        ]

        mock_result = Mock()
        mock_result.records = mock_records
        mock_graphiti_client.execute_query = AsyncMock(return_value=mock_result)

        # Make request
        response = client.post(
            "/api/v1/maintenance/deduplicate",
            json={"similarity_threshold": 0.9, "dry_run": True},
        )

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert data["dry_run"] is True
        assert data["duplicates_found"] == 1
        assert "duplicate_groups" in data


@pytest.mark.unit
class TestTasksRouter:
    """Test cases for tasks router endpoints."""

    @pytest.mark.asyncio
    async def test_get_task_stats(self, client, test_db):
        """Test getting task statistics."""
        # Make request
        response = client.get("/api/v1/tasks/stats")

        # Assert
        assert response.status_code == status.HTTP_200_OK
        data = response.json()
        assert "total" in data
        assert "pending" in data
        assert "processing" in data
        assert "completed" in data
        assert "failed" in data
        assert "throughput_per_minute" in data
        assert "error_rate" in data
