"""
Integration tests for new Memory workflow features.
Tests:
1. Update memory triggers re-processing via Temporal workflow
2. Manual reprocess rejects storage without the required transaction fence
3. Delete memory uses correct graphiti cleanup method
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.primary.web.startup.plugin_runtime_v2 import (
    initialize_plugin_runtime_v2,
    shutdown_plugin_runtime_v2,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, MemoryChunk, TaskLog


@pytest.fixture(autouse=True)
async def _memories_v2_runtime(test_app, monkeypatch):
    from src.infrastructure.agent.plugins.skill_evolution.scheduler import EvolutionScheduler

    monkeypatch.setattr(EvolutionScheduler, "start", AsyncMock())

    async def graph_runtime_factory():
        return test_app.state.graph_service

    await initialize_plugin_runtime_v2(
        test_app,
        graph_runtime_factory=graph_runtime_factory,
    )
    try:
        assert "memories" in test_app.state.platform_plugin_route_graph_v2.v2_owned_row_ids
        yield
    finally:
        await shutdown_plugin_runtime_v2(test_app)


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

    async def test_update_memory_marks_task_failed_when_workflow_start_fails(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_workflow_engine: AsyncMock,
        db: AsyncSession,
    ):
        """Test update reprocessing does not leave orphaned pending task logs."""
        update_data = {
            "title": "Updated Title with failed workflow",
            "content": "Updated content with failed workflow",
            "version": test_memory_db.version,
        }
        mock_workflow_engine.start_workflow.reset_mock()
        mock_workflow_engine.start_workflow.side_effect = RuntimeError("temporal unavailable")

        try:
            response = await async_client.patch(
                f"/api/v1/memories/{test_memory_db.id}", json=update_data
            )
        finally:
            mock_workflow_engine.start_workflow.side_effect = None

        assert response.status_code == 200
        data = response.json()
        assert data["processing_status"] == "FAILED"
        assert data["task_id"] is not None

        task_result = await db.execute(select(TaskLog).where(TaskLog.id == data["task_id"]))
        task_log = task_result.scalar_one()
        assert task_log.status == "FAILED"
        assert "temporal unavailable" in (task_log.error_message or "")

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

    async def test_reprocess_memory_rejects_missing_enrollment_fence_without_effects(
        self,
        async_client: AsyncClient,
        test_memory_db: "Memory",
        mock_workflow_engine: AsyncMock,
        mock_graph_service,
        db: AsyncSession,
    ):
        """The SQLite fixture lacks the migration-created enrollment fence row."""
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
        assert response.status_code == 503
        assert "knowledge_sync_fence_missing" in response.text
        mock_workflow_engine.start_workflow.assert_not_awaited()
        mock_graph_service.delete_episode_by_memory_id.assert_not_awaited()
        await db.refresh(test_memory_db)
        assert test_memory_db.processing_status == "COMPLETED"
        assert test_memory_db.task_id is None
        assert list((await db.scalars(select(TaskLog))).all()) == []

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
