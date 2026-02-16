"""Tests for MCPSandboxAdapter orphan container cleanup.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that orphan containers are properly cleaned up on startup
and periodically during runtime.
"""

import asyncio
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
    MCPSandboxInstance,
)


@pytest.fixture
def mock_docker():
    """Create mock Docker client."""
    mock = MagicMock()
    return mock


@pytest.fixture
def adapter(mock_docker):
    """Create MCPSandboxAdapter with mocked Docker."""
    with patch(
        "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
        return_value=mock_docker,
    ):
        adapter = MCPSandboxAdapter()
        yield adapter


class TestOrphanContainerCleanup:
    """Test enhanced orphan container cleanup functionality."""

    @pytest.mark.asyncio
    async def test_cleanup_orphans_removes_containers_without_project_id(
        self, adapter, mock_docker
    ):
        """
        RED Test: Verify that cleanup_orphans removes containers without project_id label.

        Orphan containers (no project_id) should be removed during cleanup.
        """
        # Setup: Create orphan containers (no project_id)
        orphan_container = MagicMock()
        orphan_container.name = "orphan-sandbox-123"
        orphan_container.status = "running"
        orphan_container.labels = {
            "memstack.sandbox": "true",
            # Missing memstack.project_id
        }
        orphan_container.id = "container-orphan-123"

        # Setup: Create valid container (has project_id)
        valid_container = MagicMock()
        valid_container.name = "valid-sandbox-456"
        valid_container.status = "running"
        valid_container.labels = {
            "memstack.sandbox": "true",
            "memstack.project_id": "proj-456",
        }

        mock_docker.containers.list = Mock(return_value=[orphan_container, valid_container])

        # Add valid container to active sandboxes (so it's not considered orphan)
        adapter._active_sandboxes["valid-sandbox-456"] = MCPSandboxInstance(
            id="valid-sandbox-456",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path="/tmp/project",
        )

        # Act: Run cleanup
        count = await adapter.cleanup_orphans()

        # Assert: Orphan should be removed
        assert count >= 1, "Should have cleaned up at least 1 orphan container"
        orphan_container.stop.assert_called_once()
        orphan_container.remove.assert_called_once()

        # Assert: Valid container should NOT be removed
        valid_container.stop.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_orphans_removes_exited_containers(self, adapter, mock_docker):
        """
        Test that cleanup_orphans removes containers with exited/dead status.

        Exited containers should be cleaned up even if they have project_id.
        """
        # Setup: Exited container
        exited_container = MagicMock()
        exited_container.name = "exited-sandbox-789"
        exited_container.status = "exited"
        exited_container.labels = {
            "memstack.sandbox": "true",
            "memstack.project_id": "proj-789",
        }
        exited_container.id = "container-exited-789"

        mock_docker.containers.list = Mock(return_value=[exited_container])

        # Act: Run cleanup
        count = await adapter.cleanup_orphans()

        # Assert: Exited container should be removed
        assert count >= 1, "Should have cleaned up exited container"
        exited_container.remove.assert_called()

    @pytest.mark.asyncio
    async def test_cleanup_orphans_removes_stale_containers(self, adapter, mock_docker):
        """
        Test that cleanup_orphans removes containers not in DB association.

        A container is considered stale if:
        - It's not in _active_sandboxes
        - AND it has no corresponding project_sandbox record in DB
        """
        # Setup: Container with project_id but not tracked
        stale_container = MagicMock()
        stale_container.name = "stale-sandbox-abc"
        stale_container.status = "running"
        stale_container.labels = {
            "memstack.sandbox": "true",
            "memstack.project_id": "stale-project-id",  # Has project_id
        }
        stale_container.id = "container-stale-abc"
        stale_container.attrs = {
            "Created": "2024-01-01T00:00:00Z",  # Old container
        }

        mock_docker.containers.list = Mock(return_value=[stale_container])

        # Note: This test will check DB for project_sandbox association
        # If not found, container should be removed as stale

        # Act: Run cleanup with DB check
        count = await adapter.cleanup_orphans(check_db=True)

        # Assert: Stale container should be removed
        assert count >= 1, "Should have cleaned up stale container"

    @pytest.mark.asyncio
    async def test_cleanup_orphans_preserves_active_containers(self, adapter, mock_docker):
        """
        Test that cleanup_orphans preserves containers that are properly tracked.
        """
        # Setup: Active container in memory
        active_container = MagicMock()
        active_container.name = "active-sandbox-active"
        active_container.status = "running"
        active_container.labels = {
            "memstack.sandbox": "true",
            "memstack.project_id": "proj-active",
        }

        mock_docker.containers.list = Mock(return_value=[active_container])

        # Add to active sandboxes
        adapter._active_sandboxes["active-sandbox-active"] = MCPSandboxInstance(
            id="active-sandbox-active",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="sandbox-mcp-server:latest"),
            project_path="/tmp/active_project",
        )

        # Act: Run cleanup
        count = await adapter.cleanup_orphans()

        # Assert: No containers should be removed
        assert count == 0, "Should not remove active containers"
        active_container.stop.assert_not_called()
        active_container.remove.assert_not_called()

    @pytest.mark.asyncio
    async def test_cleanup_orphans_handles_docker_errors_gracefully(
        self, adapter, mock_docker
    ):
        """
        Test that cleanup_orphans handles Docker errors gracefully.

        If one container fails to remove, others should still be processed.
        """
        # Setup: Two orphan containers
        orphan1 = MagicMock()
        orphan1.name = "orphan-1"
        orphan1.status = "running"
        orphan1.labels = {"memstack.sandbox": "true"}  # No project_id

        orphan2 = MagicMock()
        orphan2.name = "orphan-2"
        orphan2.status = "running"
        orphan2.labels = {"memstack.sandbox": "true"}  # No project_id

        # First orphan fails to remove
        orphan1.stop.side_effect = Exception("Docker error")

        mock_docker.containers.list = Mock(return_value=[orphan1, orphan2])

        # Act: Run cleanup
        count = await adapter.cleanup_orphans()

        # Assert: Second orphan should still be processed
        orphan2.stop.assert_called()
        orphan2.remove.assert_called()

        # At least one should be cleaned up
        assert count >= 1, "Should have cleaned up at least one orphan despite error"


class TestPeriodicCleanup:
    """Test periodic cleanup task functionality."""

    @pytest.mark.asyncio
    async def test_start_periodic_cleanup_creates_background_task(self, adapter):
        """
        RED Test: Verify that start_periodic_cleanup creates a background task.
        """
        # Act: Start periodic cleanup
        await adapter.start_periodic_cleanup(interval_seconds=60)

        # Assert: Background task should be created
        assert adapter._cleanup_task is not None
        assert isinstance(adapter._cleanup_task, asyncio.Task)

        # Cleanup
        await adapter.stop_periodic_cleanup()

    @pytest.mark.asyncio
    async def test_stop_periodic_cleanup_cancels_task(self, adapter):
        """
        Test that stop_periodic_cleanup cancels the background task.
        """
        # Setup: Start cleanup task
        await adapter.start_periodic_cleanup(interval_seconds=60)

        # Act: Stop cleanup
        await adapter.stop_periodic_cleanup()

        # Assert: Task should be cancelled or None
        assert adapter._cleanup_task is None or adapter._cleanup_task.cancelled()

    @pytest.mark.asyncio
    async def test_periodic_cleanup_runs_at_interval(self, adapter, mock_docker):
        """
        Test that periodic cleanup actually runs at the specified interval.
        """
        # Setup: Track cleanup calls
        cleanup_count = [0]
        original_cleanup = adapter.cleanup_orphans

        async def tracking_cleanup(**kwargs):
            cleanup_count[0] += 1
            return await original_cleanup(**kwargs)

        adapter.cleanup_orphans = tracking_cleanup

        # Mock containers.list
        mock_docker.containers.list = Mock(return_value=[])

        # Act: Start cleanup with short interval (0.1s for testing)
        await adapter.start_periodic_cleanup(interval_seconds=0.1)

        # Wait for at least 2 cleanup cycles
        await asyncio.sleep(0.35)

        # Stop cleanup
        await adapter.stop_periodic_cleanup()

        # Assert: Cleanup should have run at least 2 times
        assert cleanup_count[0] >= 2, (
            f"Expected at least 2 cleanup runs, got {cleanup_count[0]}"
        )


class TestStartupCleanup:
    """Test cleanup functionality during adapter startup."""

    @pytest.mark.asyncio
    async def test_cleanup_on_startup_removes_orphans(self, mock_docker):
        """
        Test that adapter cleans up orphan containers on startup.

        When the adapter initializes, it should remove any orphan containers.
        """
        # Setup: Orphan containers exist
        orphan = MagicMock()
        orphan.name = "startup-orphan"
        orphan.status = "running"
        orphan.labels = {"memstack.sandbox": "true"}  # No project_id

        mock_docker.containers.list = Mock(return_value=[orphan])

        # Act: Create adapter (triggers startup cleanup)
        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
            return_value=mock_docker,
        ):
            adapter = MCPSandboxAdapter()
            # Call startup cleanup explicitly
            count = await adapter.cleanup_on_startup()

        # Assert: Orphan should be cleaned up
        assert count >= 1, "Should have cleaned up orphan on startup"

    @pytest.mark.asyncio
    async def test_cleanup_on_startup_logs_summary(self, adapter, mock_docker, caplog):
        """
        Test that cleanup_on_startup logs a summary of cleaned containers.
        """
        # Setup: Multiple orphan containers
        orphans = []
        for i in range(3):
            orphan = MagicMock()
            orphan.name = f"startup-orphan-{i}"
            orphan.status = "exited"
            orphan.labels = {"memstack.sandbox": "true"}
            orphans.append(orphan)

        mock_docker.containers.list = Mock(return_value=orphans)

        # Act: Run startup cleanup
        with caplog.at_level("INFO"):
            count = await adapter.cleanup_on_startup()

        # Assert: Should log cleanup summary
        assert count == 3
        assert any("Cleaned up" in record.message for record in caplog.records)


class TestCleanupMetrics:
    """Test cleanup metrics and statistics."""

    @pytest.mark.asyncio
    async def test_get_cleanup_stats_returns_metrics(self, adapter):
        """
        Test that get_cleanup_stats returns cleanup statistics.
        """
        # Act: Get cleanup stats
        stats = adapter.get_cleanup_stats()

        # Assert: Should have expected fields
        assert "total_cleanups" in stats
        assert "containers_removed" in stats
        assert "last_cleanup_at" in stats
        assert "errors" in stats

    @pytest.mark.asyncio
    async def test_cleanup_updates_stats(self, adapter, mock_docker):
        """
        Test that running cleanup updates the statistics.
        """
        # Setup: Orphan container
        orphan = MagicMock()
        orphan.name = "stats-orphan"
        orphan.status = "exited"
        orphan.labels = {"memstack.sandbox": "true"}

        mock_docker.containers.list = Mock(return_value=[orphan])

        # Get initial stats
        initial_stats = adapter.get_cleanup_stats()
        initial_count = initial_stats["containers_removed"]

        # Act: Run cleanup
        await adapter.cleanup_orphans()

        # Get updated stats
        updated_stats = adapter.get_cleanup_stats()

        # Assert: Stats should be updated
        assert updated_stats["containers_removed"] > initial_count
        assert updated_stats["total_cleanups"] >= initial_stats["total_cleanups"]
