"""
Integration tests for new Memory workflow features.
Tests:
1. Update memory triggers re-processing via Temporal workflow
2. Manual reprocess endpoint triggers re-processing
3. Delete memory uses correct graphiti cleanup method
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import Memory, MemoryChunk


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

        # Mock async_session_factory to avoid hitting real PostgreSQL.
        # _submit_reprocessing_workflow opens a separate session for TaskLog.
        mock_task_session = MagicMock()
        mock_task_session.add = MagicMock()

        @asynccontextmanager
        async def _fake_factory():
            mock_begin = MagicMock()
            mock_begin.__aenter__ = AsyncMock(return_value=None)
            mock_begin.__aexit__ = AsyncMock(return_value=False)
            mock_task_session.begin = MagicMock(return_value=mock_begin)
            yield mock_task_session

        with patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fake_factory,
        ):
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

        # Mock async_session_factory to avoid hitting real PostgreSQL.
        # reprocess_memory opens a separate session for TaskLog.
        mock_task_session = MagicMock()
        mock_task_session.add = MagicMock()

        @asynccontextmanager
        async def _fake_factory():
            mock_begin = MagicMock()
            mock_begin.__aenter__ = AsyncMock(return_value=None)
            mock_begin.__aexit__ = AsyncMock(return_value=False)
            mock_task_session.begin = MagicMock(return_value=mock_begin)
            yield mock_task_session

        with patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            _fake_factory,
        ):
            # Act
            response = await async_client.post(f"/api/v1/memories/{test_memory_db.id}/reprocess")

        # Assert
        assert response.status_code == 200
        data = response.json()

        # Verify workflow engine was called
        assert mock_workflow_engine.start_workflow.called
        assert data["processing_status"] == "PENDING"
        assert data["task_id"] is not None

    async def test_delete_memory_uses_memory_id_graph_cleanup(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_graph_service,
        db: AsyncSession,
    ):
        """Test delete memory uses the canonical memory-id cleanup method.

        This test verifies that the dependency override chain is correctly set up:
        - The router uses get_graph_service() dependency
        - conftest.py overrides get_graph_service to return mock_graph_service
        - mock_graph_service.delete_episode_by_memory_id should be called with the memory ID
        """
        db.add(
            MemoryChunk(
                id=str(uuid4()),
                project_id=test_memory_db.project_id,
                source_type="memory",
                source_id=test_memory_db.id,
                chunk_index=0,
                content="chunk to delete",
                content_hash="hash-to-delete",
                category="fact",
            )
        )
        await db.commit()

        # Act
        response = await async_client.delete(f"/api/v1/memories/{test_memory_db.id}")

        # Assert
        assert response.status_code == 204

        assert mock_graph_service.delete_episode_by_memory_id.called
        mock_graph_service.delete_episode_by_memory_id.assert_called_with(test_memory_db.id)

        chunk_result = await db.execute(
            select(MemoryChunk).where(
                MemoryChunk.project_id == test_memory_db.project_id,
                MemoryChunk.source_type == "memory",
                MemoryChunk.source_id == test_memory_db.id,
            )
        )
        assert list(chunk_result.scalars().all()) == []
