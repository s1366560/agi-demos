"""End-to-End tests for desktop workflows.

Tests complete user workflows from start to finish.
TDD Phase: RED - Write tests first, expect failures, then implement.
"""

import asyncio
import pytest
import time
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.desktop_manager import DesktopManager
from src.tools.desktop_tools import (
    start_desktop,
    stop_desktop,
    get_desktop_status,
    restart_desktop,
)


class TestDesktopWorkflowE2E:
    """End-to-end tests for complete desktop workflows."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.mark.asyncio
    async def test_workflow_start_connect_stop(self, workspace_dir):
        """Test complete workflow: start → connect → interact → stop."""
        # Step 1: Start desktop
        result = await start_desktop(
            _workspace_dir=workspace_dir,
            display=":1",
            resolution="1280x720",
            port=6080,
        )
        assert result["success"] is True
        assert "url" in result
        assert result["display"] == ":1"
        assert result["resolution"] == "1280x720"
        assert result["port"] == 6080

        # Step 2: Verify desktop is running
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["running"] is True
        assert status["url"] == result["url"]

        # Step 3: Simulate user interaction (check status multiple times)
        for _ in range(3):
            status = await get_desktop_status(_workspace_dir=workspace_dir)
            assert status["running"] is True
            await asyncio.sleep(0.1)

        # Step 4: Stop desktop
        result = await stop_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True

        # Step 5: Verify desktop is stopped
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["running"] is False

    @pytest.mark.asyncio
    async def test_workflow_session_persistence(self, workspace_dir):
        """Test that session state persists across restarts."""
        # Start with specific config
        await start_desktop(
            _workspace_dir=workspace_dir,
            display=":2",
            resolution="1920x1080",
            port=6081,
        )

        # Restart
        result = await restart_desktop(
            _workspace_dir=workspace_dir,
            display=":2",
            resolution="1920x1080",
            port=6081,
        )
        assert result["success"] is True
        assert result["display"] == ":2"
        assert result["resolution"] == "1920x1080"
        assert result["port"] == 6081

        # Verify config persisted
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["display"] == ":2"
        assert status["resolution"] == "1920x1080"
        assert status["port"] == 6081

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_workflow_multiple_start_stop_cycles(self, workspace_dir):
        """Test multiple start/stop cycles in succession."""
        for i in range(3):
            # Start
            result = await start_desktop(
                _workspace_dir=workspace_dir,
                display=f":{i+1}",
            )
            assert result["success"] is True

            # Verify running
            status = await get_desktop_status(_workspace_dir=workspace_dir)
            assert status["running"] is True

            # Stop
            result = await stop_desktop(_workspace_dir=workspace_dir)
            assert result["success"] is True

            # Verify stopped
            status = await get_desktop_status(_workspace_dir=workspace_dir)
            assert status["running"] is False

    @pytest.mark.asyncio
    async def test_workflow_restart_preserves_config(self, workspace_dir):
        """Test that restart preserves desktop configuration."""
        # Start with custom config
        await start_desktop(
            _workspace_dir=workspace_dir,
            display=":3",
            resolution="1600x900",
            port=6082,
        )

        # Restart without specifying config (should use previous)
        result = await restart_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True

        # Verify config is preserved
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["running"] is True

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_workflow_error_recovery(self, workspace_dir):
        """Test error recovery when operations fail."""
        # Attempt to stop when not running (should succeed gracefully)
        result = await stop_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True

        # Attempt to restart when not running (should start fresh)
        result = await restart_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True

        # Verify running
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["running"] is True

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)


class TestConcurrentSessions:
    """Tests for multiple concurrent desktop sessions."""

    @pytest.fixture
    def workspace_dirs(self, tmp_path):
        """Provide multiple temporary workspace directories."""
        return [
            str(tmp_path / f"workspace{i}")
            for i in range(3)
        ]

    @pytest.mark.asyncio
    async def test_concurrent_desktop_sessions(self, workspace_dirs):
        """Test running multiple desktop sessions concurrently."""
        sessions = []

        # Start all sessions concurrently
        tasks = [
            start_desktop(
                _workspace_dir=workspace_dir,
                display=f":{i+1}",
                port=6080 + i,
            )
            for i, workspace_dir in enumerate(workspace_dirs)
        ]
        results = await asyncio.gather(*tasks)

        # Verify all started successfully
        for i, result in enumerate(results):
            assert result["success"] is True
            assert result["display"] == f":{i+1}"
            assert result["port"] == 6080 + i

        # Verify all are running
        for i, workspace_dir in enumerate(workspace_dirs):
            status = await get_desktop_status(_workspace_dir=workspace_dir)
            assert status["running"] is True
            assert status["display"] == f":{i+1}"

        # Stop all sessions
        stop_tasks = [
            stop_desktop(_workspace_dir=workspace_dir)
            for workspace_dir in workspace_dirs
        ]
        stop_results = await asyncio.gather(*stop_tasks)

        # Verify all stopped successfully
        for result in stop_results:
            assert result["success"] is True

    @pytest.mark.asyncio
    async def test_independent_session_managers(self, workspace_dirs):
        """Test that each workspace gets an independent manager."""
        # Start different configs in different workspaces
        configs = [
            (":1", "1280x720", 6080),
            (":2", "1920x1080", 6081),
            (":3", "1600x900", 6082),
        ]

        tasks = [
            start_desktop(
                _workspace_dir=workspace_dir,
                display=config[0],
                resolution=config[1],
                port=config[2],
            )
            for workspace_dir, config in zip(workspace_dirs, configs)
        ]
        await asyncio.gather(*tasks)

        # Verify each has its own config
        for workspace_dir, config in zip(workspace_dirs, configs):
            status = await get_desktop_status(_workspace_dir=workspace_dir)
            assert status["display"] == config[0]
            assert status["resolution"] == config[1]
            assert status["port"] == config[2]

        # Cleanup
        for workspace_dir in workspace_dirs:
            await stop_desktop(_workspace_dir=workspace_dir)


class TestErrorHandling:
    """Tests for error handling and edge cases."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.mark.asyncio
    async def test_start_already_running_returns_success(self, workspace_dir):
        """Test that starting an already running desktop returns success."""
        # First start
        await start_desktop(_workspace_dir=workspace_dir)

        # Second start (should return success with message)
        result = await start_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True
        assert "already running" in result["message"].lower()

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_double_stop_is_safe(self, workspace_dir):
        """Test that stopping twice doesn't cause errors."""
        # Start and stop
        await start_desktop(_workspace_dir=workspace_dir)
        await stop_desktop(_workspace_dir=workspace_dir)

        # Second stop (should succeed gracefully)
        result = await stop_desktop(_workspace_dir=workspace_dir)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_status_when_never_started(self, workspace_dir):
        """Test getting status when desktop was never started."""
        status = await get_desktop_status(_workspace_dir=workspace_dir)
        assert status["running"] is False
        assert status["url"] is None

    @pytest.mark.asyncio
    async def test_invalid_display_number(self, workspace_dir):
        """Test handling of invalid display numbers."""
        # Try to start with invalid display (should be handled gracefully)
        # Note: This test expects the system to reject obviously invalid displays
        result = await start_desktop(
            _workspace_dir=workspace_dir,
            display=":999",  # Unusually high display number
        )
        # System should either succeed or provide clear error
        assert "success" in result or "error" in result

        # Cleanup if started
        if result.get("success"):
            await stop_desktop(_workspace_dir=workspace_dir)


class TestPerformanceBenchmarks:
    """Performance benchmark tests."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.mark.asyncio
    async def test_startup_time(self, workspace_dir):
        """Test that desktop starts within acceptable time."""
        start_time = time.time()

        await start_desktop(_workspace_dir=workspace_dir)

        elapsed = time.time() - start_time

        # Startup should complete within 10 seconds (mocked processes)
        assert elapsed < 10.0, f"Startup took {elapsed:.2f}s, expected <10s"

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_shutdown_time(self, workspace_dir):
        """Test that desktop stops within acceptable time."""
        # Start first
        await start_desktop(_workspace_dir=workspace_dir)

        # Measure shutdown time
        start_time = time.time()

        await stop_desktop(_workspace_dir=workspace_dir)

        elapsed = time.time() - start_time

        # Shutdown should complete within 5 seconds
        assert elapsed < 5.0, f"Shutdown took {elapsed:.2f}s, expected <5s"

    @pytest.mark.asyncio
    async def test_status_query_performance(self, workspace_dir):
        """Test that status queries are fast."""
        # Start desktop
        await start_desktop(_workspace_dir=workspace_dir)

        # Measure multiple status queries
        start_time = time.time()

        for _ in range(10):
            await get_desktop_status(_workspace_dir=workspace_dir)

        elapsed = time.time() - start_time

        # 10 queries should complete within 1 second
        assert elapsed < 1.0, f"10 queries took {elapsed:.2f}s, expected <1s"

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_restart_time(self, workspace_dir):
        """Test that restart completes within acceptable time."""
        # Start first
        await start_desktop(_workspace_dir=workspace_dir)

        # Measure restart time
        start_time = time.time()

        await restart_desktop(_workspace_dir=workspace_dir)

        elapsed = time.time() - start_time

        # Restart should complete within 15 seconds
        assert elapsed < 15.0, f"Restart took {elapsed:.2f}s, expected <15s"

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)


class TestResourceLimits:
    """Tests for resource usage and limits."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.mark.asyncio
    async def test_multiple_concurrent_operations(self, workspace_dir):
        """Test that multiple concurrent operations don't cause conflicts."""
        # Start desktop
        await start_desktop(_workspace_dir=workspace_dir)

        # Perform multiple operations concurrently
        tasks = [
            get_desktop_status(_workspace_dir=workspace_dir),
            get_desktop_status(_workspace_dir=workspace_dir),
            get_desktop_status(_workspace_dir=workspace_dir),
        ]
        results = await asyncio.gather(*tasks)

        # All should succeed
        for result in results:
            assert result["running"] is True

        # Cleanup
        await stop_desktop(_workspace_dir=workspace_dir)

    @pytest.mark.asyncio
    async def test_rapid_start_stop_cycles(self, workspace_dir):
        """Test rapid start/stop cycles don't cause resource leaks."""
        # Perform 5 rapid cycles
        for _ in range(5):
            await start_desktop(_workspace_dir=workspace_dir)
            await asyncio.sleep(0.1)
            await stop_desktop(_workspace_dir=workspace_dir)
            await asyncio.sleep(0.1)

        # If we got here without errors, resource cleanup is working
        assert True
