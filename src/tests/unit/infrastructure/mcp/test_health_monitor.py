"""Unit tests for MCP Server Health Monitor."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.mcp.health_monitor import (
    MCPServerHealth,
    MCPServerHealthMonitor,
    MCPServerResourceUsage,
)


@pytest.mark.unit
class TestMCPServerHealth:
    """Tests for MCPServerHealth dataclass."""

    def test_health_creation_default(self):
        """Test creating health with default values."""
        now = datetime.utcnow()
        health = MCPServerHealth(
            name="test-server",
            status="healthy",
            last_check=now,
        )

        assert health.name == "test-server"
        assert health.status == "healthy"
        assert health.last_check == now
        assert health.error_message is None
        assert health.restart_count == 0

    def test_health_creation_with_error(self):
        """Test creating health with error message."""
        now = datetime.utcnow()
        health = MCPServerHealth(
            name="test-server",
            status="unhealthy",
            last_check=now,
            error_message="Connection refused",
            restart_count=2,
        )

        assert health.status == "unhealthy"
        assert health.error_message == "Connection refused"
        assert health.restart_count == 2


@pytest.mark.unit
class TestMCPServerResourceUsage:
    """Tests for MCPServerResourceUsage dataclass."""

    def test_resource_usage_creation(self):
        """Test creating resource usage."""
        usage = MCPServerResourceUsage(
            server_name="test-server",
            cpu_percent=45.5,
            memory_mb=256.0,
            uptime_seconds=3600,
        )

        assert usage.server_name == "test-server"
        assert usage.cpu_percent == 45.5
        assert usage.memory_mb == 256.0
        assert usage.uptime_seconds == 3600

    def test_resource_usage_defaults(self):
        """Test resource usage with defaults."""
        usage = MCPServerResourceUsage(server_name="test-server")

        assert usage.cpu_percent is None
        assert usage.memory_mb is None
        assert usage.uptime_seconds is None


@pytest.mark.unit
class TestMCPServerHealthMonitor:
    """Tests for MCPServerHealthMonitor."""

    @pytest.fixture
    def mock_sandbox_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def monitor(self, mock_sandbox_adapter):
        """Create a health monitor instance."""
        return MCPServerHealthMonitor(
            sandbox_adapter=mock_sandbox_adapter,
            check_interval_seconds=30.0,
        )

    async def test_health_check_healthy(self, monitor, mock_sandbox_adapter):
        """Test health check for healthy server."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '[{"name": "test-server", "status": "running", "pid": 1234}]',
                }
            ],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "healthy"
        assert health.name == "test-server"
        assert health.error_message is None
        mock_sandbox_adapter.call_tool.assert_called_once()

    async def test_health_check_unhealthy_stopped(self, monitor, mock_sandbox_adapter):
        """Test health check for stopped server."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "stopped" in (health.error_message or "").lower()

    async def test_health_check_unhealthy_not_found(self, monitor, mock_sandbox_adapter):
        """Test health check when server not in list."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "[]"}],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "not found" in (health.error_message or "").lower()

    async def test_health_check_unhealthy_error(self, monitor, mock_sandbox_adapter):
        """Test health check when server call fails."""
        mock_sandbox_adapter.call_tool.side_effect = ConnectionError("Sandbox unreachable")

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "Sandbox unreachable" in (health.error_message or "")

    async def test_health_check_unknown_status(self, monitor, mock_sandbox_adapter):
        """Test health check with unknown server status."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "weird"}]'}],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unknown"

    async def test_restart_if_unhealthy_success(self, monitor, mock_sandbox_adapter):
        """Test successful restart of unhealthy server."""
        # First call: health check (list) returns stopped
        # Second call: stop
        # Third call: install
        # Fourth call: start
        mock_sandbox_adapter.call_tool.side_effect = [
            {
                "content": [
                    {"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}
                ],
                "is_error": False,
            },
            {"content": [{"type": "text", "text": '{"success": true}'}], "is_error": False},
            {"content": [{"type": "text", "text": '{"success": true}'}], "is_error": False},
            {
                "content": [{"type": "text", "text": '{"success": true, "status": "running"}'}],
                "is_error": False,
            },
        ]

        # Set up _get_server_config to return config
        with patch.object(
            monitor,
            "_get_server_config",
            return_value={
                "server_type": "stdio",
                "transport_config": {"command": "node", "args": ["server.js"]},
            },
        ):
            restarted = await monitor.restart_if_unhealthy(
                "sandbox-1",
                "test-server",
                max_restarts=3,
            )

        assert restarted is True
        assert mock_sandbox_adapter.call_tool.call_count == 4

    async def test_restart_if_unhealthy_already_healthy(self, monitor, mock_sandbox_adapter):
        """Test that healthy server is not restarted."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '[{"name": "test-server", "status": "running", "pid": 1234}]',
                }
            ],
            "is_error": False,
        }

        restarted = await monitor.restart_if_unhealthy("sandbox-1", "test-server")

        assert restarted is False
        mock_sandbox_adapter.call_tool.assert_called_once()  # Only health check

    async def test_restart_if_unhealthy_max_restarts_exceeded(self, monitor, mock_sandbox_adapter):
        """Test restart fails when max restarts exceeded."""
        # Simulate server that keeps failing
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}],
            "is_error": False,
        }

        # Pre-increment restart count
        monitor._restart_counts["sandbox-1:test-server"] = 3

        restarted = await monitor.restart_if_unhealthy(
            "sandbox-1",
            "test-server",
            max_restarts=3,
        )

        assert restarted is False

    async def test_restart_if_unhealthy_install_fails(self, monitor, mock_sandbox_adapter):
        """Test restart fails when install fails."""
        mock_sandbox_adapter.call_tool.side_effect = [
            {
                "content": [
                    {"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}
                ],
                "is_error": False,
            },
            {"content": [{"type": "text", "text": '{"success": true}'}], "is_error": False},  # stop
            {
                "content": [
                    {"type": "text", "text": '{"success": false, "error": "npm not found"}'}
                ],
                "is_error": False,
            },
        ]

        with patch.object(
            monitor,
            "_get_server_config",
            return_value={
                "server_type": "stdio",
                "transport_config": {"command": "node"},
            },
        ):
            restarted = await monitor.restart_if_unhealthy("sandbox-1", "test-server")

        assert restarted is False

    async def test_get_resource_usage_success(self, monitor, mock_sandbox_adapter):
        """Test getting resource usage."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"cpu_percent": 25.5, "memory_mb": 128.0, "uptime_seconds": 7200}',
                }
            ],
            "is_error": False,
        }

        usage = await monitor.get_resource_usage("sandbox-1", "test-server")

        assert usage is not None
        assert usage.server_name == "test-server"
        assert usage.cpu_percent == 25.5
        assert usage.memory_mb == 128.0
        assert usage.uptime_seconds == 7200

    async def test_get_resource_usage_failure(self, monitor, mock_sandbox_adapter):
        """Test resource usage returns None on failure."""
        mock_sandbox_adapter.call_tool.side_effect = TimeoutError("Request timeout")

        usage = await monitor.get_resource_usage("sandbox-1", "test-server")

        assert usage is None

    async def test_start_monitoring(self, monitor, mock_sandbox_adapter):
        """Test starting background monitoring."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "running"}]'}],
            "is_error": False,
        }

        # Start monitoring (will run in background)
        await monitor.start_monitoring("sandbox-1")

        # Give it time to start
        await asyncio.sleep(0.1)

        assert "sandbox-1" in monitor._monitoring_tasks
        assert monitor._monitoring_tasks["sandbox-1"] is not None

        # Stop monitoring to clean up
        await monitor.stop_monitoring("sandbox-1")

    async def test_stop_monitoring(self, monitor, mock_sandbox_adapter):
        """Test stopping monitoring."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "running"}]'}],
            "is_error": False,
        }

        # Start then stop
        await monitor.start_monitoring("sandbox-1")
        await asyncio.sleep(0.1)

        await monitor.stop_monitoring("sandbox-1")

        assert "sandbox-1" not in monitor._monitoring_tasks

    async def test_stop_monitoring_not_running(self, monitor):
        """Test stopping monitoring when not running."""
        # Should not raise
        await monitor.stop_monitoring("nonexistent-sandbox")

    async def test_monitoring_loop_restarts_unhealthy(self, monitor, mock_sandbox_adapter):
        """Test that monitoring loop restarts unhealthy servers."""
        call_count = 0

        def mock_call(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                # First health check: unhealthy (server list shows stopped)
                return {
                    "content": [
                        {"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}
                    ],
                    "is_error": False,
                }
            elif call_count == 3:
                # Stop
                return {
                    "content": [{"type": "text", "text": '{"success": true}'}],
                    "is_error": False,
                }
            elif call_count == 4:
                # Install
                return {
                    "content": [{"type": "text", "text": '{"success": true}'}],
                    "is_error": False,
                }
            elif call_count == 5:
                # Start
                return {
                    "content": [{"type": "text", "text": '{"success": true}'}],
                    "is_error": False,
                }
            else:
                # Subsequent health checks: healthy
                return {
                    "content": [
                        {"type": "text", "text": '[{"name": "test-server", "status": "running"}]'}
                    ],
                    "is_error": False,
                }

        mock_sandbox_adapter.call_tool.side_effect = mock_call

        # Mock get_monitored_servers to return test server
        with patch.object(
            monitor,
            "_get_monitored_servers",
            return_value=[("test-server", "stdio", {})],
        ):
            # Use short interval for testing
            monitor._check_interval_seconds = 0.1
            await monitor.start_monitoring("sandbox-1")

            # Wait for at least one check cycle
            await asyncio.sleep(0.3)

            # Stop monitoring
            await monitor.stop_monitoring("sandbox-1")

        # Should have attempted restart
        assert call_count >= 3

    async def test_graceful_shutdown(self, monitor, mock_sandbox_adapter):
        """Test graceful shutdown stops all monitoring."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "running"}]'}],
            "is_error": False,
        }

        # Start multiple monitoring tasks
        await monitor.start_monitoring("sandbox-1")
        await monitor.start_monitoring("sandbox-2")
        await asyncio.sleep(0.1)

        # Shutdown all
        await monitor.shutdown()

        assert len(monitor._monitoring_tasks) == 0

    async def test_health_check_updates_restart_count(self, monitor, mock_sandbox_adapter):
        """Test that health check tracks restart counts."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "running"}]'}],
            "is_error": False,
        }

        # Set existing restart count
        monitor._restart_counts["sandbox-1:test-server"] = 2

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.restart_count == 2

    async def test_health_check_timeout(self, monitor, mock_sandbox_adapter):
        """Test health check with timeout."""

        async def slow_call(*args, **kwargs):
            await asyncio.sleep(20)  # Longer than timeout
            return {"content": [], "is_error": False}

        mock_sandbox_adapter.call_tool = slow_call
        monitor._health_check_timeout = 0.1

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "timed out" in (health.error_message or "").lower()

    async def test_health_check_failed_status(self, monitor, mock_sandbox_adapter):
        """Test health check with failed server status."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "failed"}]'}],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "failed" in (health.error_message or "").lower()

    async def test_health_check_crashed_status(self, monitor, mock_sandbox_adapter):
        """Test health check with crashed server status."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "crashed"}]'}],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "unhealthy"
        assert "crashed" in (health.error_message or "").lower()

    async def test_health_check_wrapped_response(self, monitor, mock_sandbox_adapter):
        """Test health check with wrapped server list response."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"servers": [{"name": "test-server", "status": "running"}]}',
                }
            ],
            "is_error": False,
        }

        health = await monitor.health_check("sandbox-1", "test-server")

        assert health.status == "healthy"

    async def test_register_and_unregister_server(self, monitor):
        """Test server registration for monitoring."""
        monitor.register_server(
            "sandbox-1",
            "test-server",
            "stdio",
            {"command": "node"},
        )

        config = monitor._get_server_config("sandbox-1", "test-server")
        assert config is not None
        assert config["server_type"] == "stdio"

        monitor.unregister_server("sandbox-1", "test-server")
        config = monitor._get_server_config("sandbox-1", "test-server")
        assert config is None

    async def test_reset_restart_count(self, monitor):
        """Test resetting restart count."""
        monitor._restart_counts["sandbox-1:test-server"] = 5
        monitor.reset_restart_count("test-server", sandbox_id="sandbox-1")

        assert "sandbox-1:test-server" not in monitor._restart_counts

    async def test_start_monitoring_already_running(self, monitor, mock_sandbox_adapter):
        """Test starting monitoring when already running."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "[]"}],
            "is_error": False,
        }

        await monitor.start_monitoring("sandbox-1")
        await asyncio.sleep(0.05)

        # Should not create a second task
        await monitor.start_monitoring("sandbox-1")

        assert len(monitor._monitoring_tasks) == 1

        await monitor.stop_monitoring("sandbox-1")

    async def test_restart_if_unhealthy_no_config(self, monitor, mock_sandbox_adapter):
        """Test restart fails when no config is available."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}],
            "is_error": False,
        }

        # No config registered
        restarted = await monitor.restart_if_unhealthy("sandbox-1", "test-server")

        assert restarted is False

    async def test_restart_if_unhealthy_start_fails(self, monitor, mock_sandbox_adapter):
        """Test restart fails when start fails."""
        mock_sandbox_adapter.call_tool.side_effect = [
            {
                "content": [
                    {"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}
                ],
                "is_error": False,
            },
            {"content": [{"type": "text", "text": '{"success": true}'}], "is_error": False},  # stop
            {
                "content": [{"type": "text", "text": '{"success": true}'}],
                "is_error": False,
            },  # install
            {
                "content": [{"type": "text", "text": '{"success": false, "error": "port in use"}'}],
                "is_error": False,
            },  # start fails
        ]

        with patch.object(
            monitor,
            "_get_server_config",
            return_value={
                "server_type": "stdio",
                "transport_config": {"command": "node"},
            },
        ):
            restarted = await monitor.restart_if_unhealthy("sandbox-1", "test-server")

        assert restarted is False

    async def test_restart_if_unhealthy_exception(self, monitor, mock_sandbox_adapter):
        """Test restart handles exception during restart."""
        mock_sandbox_adapter.call_tool.side_effect = [
            {
                "content": [
                    {"type": "text", "text": '[{"name": "test-server", "status": "stopped"}]'}
                ],
                "is_error": False,
            },
            RuntimeError("Unexpected error"),
        ]

        with patch.object(
            monitor,
            "_get_server_config",
            return_value={
                "server_type": "stdio",
                "transport_config": {"command": "node"},
            },
        ):
            restarted = await monitor.restart_if_unhealthy("sandbox-1", "test-server")

        assert restarted is False
