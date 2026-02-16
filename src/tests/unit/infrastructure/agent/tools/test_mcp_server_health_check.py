"""Tests for MCP Server health check and auto-restart functionality.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that crashed MCP servers are automatically detected
and restarted by the background health check task.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestMCPServerHealthCheck:
    """Test MCP Server health check and auto-restart functionality."""

    @pytest.mark.asyncio
    async def test_start_health_check_creates_background_task(self):
        """
        RED Test: Verify that start_health_check creates a background task.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()

        # Act: Start health check
        await adapter.start_mcp_server_health_check(interval_seconds=60)

        # Assert: Background task should be created
        assert adapter._health_check_task is not None
        assert isinstance(adapter._health_check_task, asyncio.Task)

        # Cleanup
        await adapter.stop_mcp_server_health_check()

    @pytest.mark.asyncio
    async def test_stop_health_check_cancels_task(self):
        """
        Test that stop_health_check cancels the background task.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()

        # Setup: Start health check
        await adapter.start_mcp_server_health_check(interval_seconds=60)

        # Act: Stop health check
        await adapter.stop_mcp_server_health_check()

        # Assert: Task should be cancelled or None
        assert adapter._health_check_task is None or adapter._health_check_task.cancelled()

    @pytest.mark.asyncio
    async def test_health_check_detects_crashed_servers(self):
        """
        Test that health check detects servers that have crashed.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        mock_docker = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
            return_value=mock_docker,
        ):
            adapter = MCPSandboxAdapter()

        # Mock mcp_server_list to return servers with crashed status
        mock_mcp_client = AsyncMock()
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": '{"servers": [{"name": "server1", "status": "crashed"}, {"name": "server2", "status": "running"}]}',
                    }
                ]
            }
        )

        # Add sandbox with MCP client
        from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxInstance,
        )

        instance = MCPSandboxInstance(
            id="sandbox-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="test"),
            project_path="/tmp",
            mcp_client=mock_mcp_client,
        )
        adapter._active_sandboxes["sandbox-1"] = instance

        # Mock _restart_crashed_server
        adapter._restart_crashed_server = AsyncMock(return_value=True)

        # Act: Run health check
        result = await adapter._check_mcp_servers_health("sandbox-1")

        # Assert: Should have detected crashed server
        assert "server1" in result.get("crashed", [])
        assert "server2" not in result.get("crashed", [])

    @pytest.mark.asyncio
    async def test_health_check_restarts_crashed_servers(self):
        """
        Test that health check automatically restarts crashed servers.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        mock_docker = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
            return_value=mock_docker,
        ):
            adapter = MCPSandboxAdapter()

        # Mock mcp_server_list to return crashed server
        mock_mcp_client = AsyncMock()
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "content": [
                    {
                        "type": "text",
                        "text": '{"servers": [{"name": "crashed-server", "status": "crashed"}]}',
                    }
                ]
            }
        )

        from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxInstance,
        )

        instance = MCPSandboxInstance(
            id="sandbox-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="test"),
            project_path="/tmp",
            mcp_client=mock_mcp_client,
        )
        adapter._active_sandboxes["sandbox-1"] = instance

        # Track restart calls
        restart_calls = []

        async def track_restart(sandbox_id, server_name):
            restart_calls.append((sandbox_id, server_name))
            return True

        adapter._restart_crashed_server = track_restart

        # Act: Run health check with auto-restart
        await adapter._check_mcp_servers_health("sandbox-1", auto_restart=True)

        # Assert: Should have attempted restart
        assert len(restart_calls) == 1
        assert restart_calls[0] == ("sandbox-1", "crashed-server")

    @pytest.mark.asyncio
    async def test_restart_crashed_server_calls_mcp_server_start(self):
        """
        Test that _restart_crashed_server calls mcp_server_start.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        mock_docker = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
            return_value=mock_docker,
        ):
            adapter = MCPSandboxAdapter()

        # Mock successful restart
        mock_mcp_client = AsyncMock()
        mock_mcp_client.call_tool = AsyncMock(
            return_value={
                "content": [{"type": "text", "text": '{"success": true}'}],
                "is_error": False,
            }
        )

        from src.domain.ports.services.sandbox_port import SandboxConfig, SandboxStatus
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxInstance,
        )

        instance = MCPSandboxInstance(
            id="sandbox-1",
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image="test"),
            project_path="/tmp",
            mcp_client=mock_mcp_client,
        )
        adapter._active_sandboxes["sandbox-1"] = instance

        # Store server config for restart
        adapter._mcp_server_configs = {
            ("sandbox-1", "my-server"): {
                "server_type": "stdio",
                "transport_config": '{"command": "node", "args": ["server.js"]}',
            }
        }

        # Act: Restart crashed server
        result = await adapter._restart_crashed_server("sandbox-1", "my-server")

        # Assert: Should have called mcp_server_start
        assert result is True
        assert mock_mcp_client.call_tool.call_count >= 1

    @pytest.mark.asyncio
    async def test_periodic_health_check_runs_at_interval(self):
        """
        Test that periodic health check actually runs at the specified interval.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        mock_docker = MagicMock()

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env",
            return_value=mock_docker,
        ):
            adapter = MCPSandboxAdapter()

        # Track health check calls
        check_count = [0]
        original_check = adapter._run_health_check_cycle

        async def tracking_check():
            check_count[0] += 1
            if hasattr(original_check, "__func__"):
                return await original_check(adapter)

        adapter._run_health_check_cycle = tracking_check

        # Act: Start with short interval
        await adapter.start_mcp_server_health_check(interval_seconds=0.1)

        # Wait for at least 2 cycles
        await asyncio.sleep(0.35)

        # Stop
        await adapter.stop_mcp_server_health_check()

        # Assert: Should have run at least 2 times
        assert check_count[0] >= 2, f"Expected at least 2 checks, got {check_count[0]}"


class TestMCPServerHealthStats:
    """Test health check statistics and monitoring."""

    @pytest.mark.asyncio
    async def test_get_health_check_stats(self):
        """
        Test that get_health_check_stats returns health statistics.
        """
        from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
            MCPSandboxAdapter,
        )

        with patch(
            "src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter.docker.from_env"
        ):
            adapter = MCPSandboxAdapter()

        # Act: Get stats
        stats = adapter.get_health_check_stats()

        # Assert: Should have expected fields
        assert "total_checks" in stats
        assert "restarts_triggered" in stats
        assert "last_check_at" in stats
        assert "errors" in stats
