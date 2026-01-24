"""
Integration tests for new Memory workflow features.
Tests:
1. Update memory triggers re-processing via Temporal workflow
2. Manual reprocess endpoint triggers re-processing
3. Delete memory uses correct graphiti cleanup method
"""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import Memory


@pytest.mark.asyncio
class TestMemoryWorkflowNew:
    """Test new workflow features for Memory."""

    async def test_update_memory_triggers_reprocessing(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_workflow_engine: AsyncMock,
    ):
        """Test that updating memory content triggers re-processing via Temporal workflow."""
        # Arrange
        update_data = {
            "title": "Updated Title triggers reprocess",
            "content": "Updated content triggers reprocess",
            "version": test_memory_db.version,
        }

        # Reset mock calls
        mock_workflow_engine.start_workflow.reset_mock()

        # Act
        response = await async_client.patch(
            f"/api/v1/memories/{test_memory_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify workflow engine was called
        assert mock_workflow_engine.start_workflow.called
        assert data["processing_status"] == "PENDING"
        assert data["task_id"] is not None

    async def test_update_memory_no_reprocess_on_metadata_change(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_workflow_engine: AsyncMock,
    ):
        """Test that updating only metadata (e.g. tags) does NOT trigger re-processing."""
        # Arrange
        update_data = {
            "tags": ["new-tag"],
            "version": test_memory_db.version,
        }

        # Reset mock calls
        mock_workflow_engine.start_workflow.reset_mock()

        # Act
        response = await async_client.patch(
            f"/api/v1/memories/{test_memory_db.id}", json=update_data
        )

        # Assert
        assert response.status_code == 200

        # Verify workflow engine was NOT called
        assert not mock_workflow_engine.start_workflow.called

    @pytest.mark.skip(
        reason="Requires real PostgreSQL + Temporal infrastructure. "
        "The endpoint uses async_session_factory() which connects to production DB."
    )
    async def test_reprocess_memory_endpoint(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_workflow_engine: AsyncMock,
        db: AsyncSession,
    ):
        """Test manual reprocess endpoint triggers Temporal workflow."""
        # Arrange - set memory status to COMPLETED so we can reprocess it
        await db.execute(
            update(Memory)
            .where(Memory.id == test_memory_db.id)
            .values(processing_status="COMPLETED")
        )
        await db.commit()

        # Reset mock calls
        mock_workflow_engine.start_workflow.reset_mock()

        # Act
        response = await async_client.post(f"/api/v1/memories/{test_memory_db.id}/reprocess")

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify workflow engine was called
        assert mock_workflow_engine.start_workflow.called
        assert data["processing_status"] == "PENDING"
        assert data["task_id"] is not None

    async def test_delete_memory_uses_graphiti_remove(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_graph_service,
        db: AsyncSession,
    ):
        """Test delete memory uses correct graphiti remove_episode method.

        This test verifies that the dependency override chain is correctly set up:
        - The router uses get_graph_service() dependency
        - conftest.py overrides get_graph_service to return mock_graph_service
        - mock_graph_service.remove_episode should be called with the memory ID
        """
        # Act
        response = await async_client.delete(f"/api/v1/memories/{test_memory_db.id}")

        # Assert
        assert response.status_code == 204

        # Verify graph_service.remove_episode was called
        # The router now uses graph_service.remove_episode(memory_id) directly
        assert mock_graph_service.remove_episode.called
        mock_graph_service.remove_episode.assert_called_with(test_memory_db.id)
