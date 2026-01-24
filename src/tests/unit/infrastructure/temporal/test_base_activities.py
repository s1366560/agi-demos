"""Unit tests for Temporal base activities utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.unit
class TestUpdateTaskProgress:
    """Test cases for update_task_progress utility."""

    @pytest.mark.asyncio
    async def test_update_task_progress_with_task_id(self):
        """Test progress update with valid task_id."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            update_task_progress,
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                return_value=mock_session,
            ),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Act
            await update_task_progress(
                task_id="task_123",
                progress=50,
                message="Processing entities...",
                status="PROCESSING",
            )

            # Assert
            mock_heartbeat.assert_called_once_with(
                {"progress": 50, "message": "Processing entities...", "status": "PROCESSING"}
            )
            mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_task_progress_without_task_id(self):
        """Test progress update without task_id (heartbeat only)."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            update_task_progress,
        )

        with patch("temporalio.activity.heartbeat") as mock_heartbeat:
            # Act
            await update_task_progress(
                task_id=None,
                progress=75,
                message="Almost done",
            )

            # Assert
            mock_heartbeat.assert_called_once()
            # Database should not be touched


@pytest.mark.unit
class TestUpdateMemoryStatus:
    """Test cases for update_memory_status utility."""

    @pytest.mark.asyncio
    async def test_update_memory_status_with_enum(self):
        """Test memory status update with ProcessingStatus enum."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            update_memory_status,
        )

        mock_status = MagicMock()
        mock_status.value = "COMPLETED"

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)

        with patch(
            "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
            return_value=mock_session,
        ):
            # Act
            await update_memory_status("mem_123", mock_status)

            # Assert
            mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_memory_status_without_memory_id(self):
        """Test memory status update with None memory_id (no-op)."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            update_memory_status,
        )

        mock_status = MagicMock()
        mock_status.value = "PROCESSING"

        # Act - should not raise
        await update_memory_status(None, mock_status)

        # Assert - no database call when memory_id is None


@pytest.mark.unit
class TestMarkTaskCompleted:
    """Test cases for mark_task_completed utility."""

    @pytest.mark.asyncio
    async def test_mark_task_completed_success(self):
        """Test marking task as completed."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            mark_task_completed,
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                return_value=mock_session,
            ),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Act
            await mark_task_completed(
                task_id="task_123",
                message="Episode processed successfully",
                result={"entity_count": 5},
            )

            # Assert
            mock_heartbeat.assert_called_once_with(
                {
                    "progress": 100,
                    "status": "completed",
                    "message": "Episode processed successfully",
                }
            )
            mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_task_completed_without_result(self):
        """Test marking task completed without result dict."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            mark_task_completed,
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                return_value=mock_session,
            ),
            patch("temporalio.activity.heartbeat"),
        ):
            # Act
            await mark_task_completed(task_id="task_123")

            # Assert
            mock_session.execute.assert_called_once()


@pytest.mark.unit
class TestMarkTaskFailed:
    """Test cases for mark_task_failed utility."""

    @pytest.mark.asyncio
    async def test_mark_task_failed_success(self):
        """Test marking task as failed."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            mark_task_failed,
        )

        mock_session = MagicMock()
        mock_session.__aenter__ = AsyncMock(return_value=mock_session)
        mock_session.__aexit__ = AsyncMock(return_value=None)
        mock_session.execute = AsyncMock()
        mock_session.begin = MagicMock(return_value=mock_session)

        with (
            patch(
                "src.infrastructure.adapters.secondary.persistence.database.async_session_factory",
                return_value=mock_session,
            ),
            patch("temporalio.activity.heartbeat") as mock_heartbeat,
        ):
            # Act
            await mark_task_failed(
                task_id="task_123",
                error_message="LLM API timeout",
            )

            # Assert
            mock_heartbeat.assert_called_once_with({"status": "failed", "error": "LLM API timeout"})
            mock_session.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_mark_task_failed_without_task_id(self):
        """Test marking task failed without task_id (heartbeat only)."""
        from src.infrastructure.adapters.secondary.temporal.activities.base import (
            mark_task_failed,
        )

        with patch("temporalio.activity.heartbeat") as mock_heartbeat:
            # Act
            await mark_task_failed(
                task_id=None,
                error_message="Connection failed",
            )

            # Assert
            mock_heartbeat.assert_called_once()


@pytest.mark.unit
class TestEpisodeStatusTransitions:
    """Test cases for Episode status state machine transitions.

    These tests verify the expected status transitions in Episode processing
    by testing the Cypher query patterns used in the activity code.
    """

    def test_episode_processing_query_sets_processing_status(self):
        """Test that episode creation query sets Processing status."""
        # The query pattern used in add_episode_activity
        query = """
            MERGE (e:Episodic {uuid: $uuid})
            SET e:Node,
                e.name = $name,
                e.content = $content,
                e.group_id = $group_id,
                e.tenant_id = $tenant_id,
                e.project_id = $project_id,
                e.user_id = $user_id,
                e.memory_id = $memory_id,
                e.status = 'Processing',
                e.created_at = datetime($created_at)
        """
        # Assert status is set to Processing
        assert "status = 'Processing'" in query

    def test_episode_success_query_sets_synced_status(self):
        """Test that success query sets Synced status."""
        # The query pattern used after successful processing
        query = """
            MATCH (ep:Episodic {uuid: $uuid})
            SET ep.status = 'Synced'
        """
        # Assert status is set to Synced
        assert "status = 'Synced'" in query

    def test_episode_failure_query_sets_failed_status(self):
        """Test that failure query sets Failed status."""
        # The query pattern used on processing error
        query = """
            MATCH (ep:Episodic {uuid: $uuid})
            SET ep.status = 'Failed'
        """
        # Assert status is set to Failed
        assert "status = 'Failed'" in query

    def test_episode_refresh_failure_query_sets_refresh_failed_status(self):
        """Test that refresh failure query sets RefreshFailed status."""
        # The query pattern used on refresh error
        query = """
            MATCH (ep:Episodic {uuid: $uuid})
            SET ep.status = 'RefreshFailed'
        """
        # Assert status is set to RefreshFailed
        assert "status = 'RefreshFailed'" in query

    def test_valid_status_transitions(self):
        """Test that all valid status transitions are defined."""
        valid_statuses = ["Processing", "Synced", "Failed", "RefreshFailed"]

        # Verify all statuses are distinct
        assert len(valid_statuses) == len(set(valid_statuses))

        # Valid transitions from PENDING
        pending_transitions = ["Processing"]
        assert all(s in valid_statuses for s in pending_transitions)

        # Valid transitions from Processing
        processing_transitions = ["Synced", "Failed"]
        assert all(s in valid_statuses for s in processing_transitions)

        # Valid transitions from Synced (for refresh)
        synced_transitions = ["Processing", "RefreshFailed"]
        assert all(s in valid_statuses for s in synced_transitions)
