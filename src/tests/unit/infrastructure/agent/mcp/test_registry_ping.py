"""Unit tests for MCPServerRegistry ping-based health check.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

Priority 1: Ping Health Check Integration
- Modify MCPServerRegistry.health_check() to use client.ping() instead of list_tools()
- This is more efficient as ping is a lightweight operation
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.infrastructure.agent.mcp.registry import MCPServerRegistry


@pytest.mark.unit
class TestMCPServerRegistryPingHealthCheck:
    """Tests for ping-based health check in MCPServerRegistry."""

    @pytest.fixture
    def registry(self):
        """Create a registry instance for testing."""
        return MCPServerRegistry(
            cache_ttl_seconds=300,
            health_check_interval_seconds=60,
            max_reconnect_attempts=3,
        )

    @pytest.fixture
    def mock_client_with_ping(self):
        """Create a mock MCPClient with ping method."""
        client = MagicMock()
        client.ping = AsyncMock(return_value=True)
        client.list_tools = AsyncMock(return_value=[])
        return client

    async def test_health_check_uses_ping_method(self, registry, mock_client_with_ping):
        """Test that health_check uses ping() instead of list_tools().

        RED Test: This test verifies that the health check method
        calls the more efficient ping() method instead of list_tools().
        """
        # Register a mock client
        registry._clients["test-server"] = mock_client_with_ping

        # Call health check
        is_healthy = await registry.health_check("test-server")

        # Verify ping was called
        assert is_healthy is True
        mock_client_with_ping.ping.assert_called_once()
        # list_tools should NOT be called
        mock_client_with_ping.list_tools.assert_not_called()

    async def test_health_check_ping_returns_false_on_failure(self, registry, mock_client_with_ping):
        """Test that health check returns False when ping fails."""
        # Configure ping to return False
        mock_client_with_ping.ping.return_value = False

        # Register the mock client
        registry._clients["test-server"] = mock_client_with_ping

        # Call health check
        is_healthy = await registry.health_check("test-server")

        # Should return False
        assert is_healthy is False
        mock_client_with_ping.ping.assert_called_once()

    async def test_health_check_ping_handles_exception(self, registry, mock_client_with_ping):
        """Test that health check handles exceptions from ping."""
        # Configure ping to raise exception
        mock_client_with_ping.ping.side_effect = RuntimeError("Connection lost")

        # Register the mock client
        registry._clients["test-server"] = mock_client_with_ping

        # Call health check - should not raise
        is_healthy = await registry.health_check("test-server")

        # Should return False on exception
        assert is_healthy is False

    async def test_health_check_returns_false_for_unregistered_server(self, registry):
        """Test that health check returns False for unregistered server."""
        is_healthy = await registry.health_check("nonexistent-server")
        assert is_healthy is False

    async def test_health_check_updates_health_status(self, registry, mock_client_with_ping):
        """Test that health check updates internal health status."""
        # Register the mock client
        registry._clients["test-server"] = mock_client_with_ping

        # Call health check
        await registry.health_check("test-server")

        # Verify health status was updated
        status = registry.get_health_status("test-server")
        assert status is not None
        is_healthy, last_check = status
        assert is_healthy is True

    async def test_health_check_status_updated_on_failure(self, registry, mock_client_with_ping):
        """Test that health status is updated when health check fails."""
        # Configure ping to return False
        mock_client_with_ping.ping.return_value = False

        # Register the mock client
        registry._clients["test-server"] = mock_client_with_ping

        # Call health check
        await registry.health_check("test-server")

        # Verify health status was updated to unhealthy
        status = registry.get_health_status("test-server")
        assert status is not None
        is_healthy, last_check = status
        assert is_healthy is False


@pytest.mark.unit
class TestMCPServerRegistryLoggingControl:
    """Tests for logging level control in MCPServerRegistry.

    Priority 1: Logging Control Integration
    - Add set_server_logging_level() method to registry
    - Allows dynamic control of server logging verbosity
    """

    @pytest.fixture
    def registry(self):
        """Create a registry instance for testing."""
        return MCPServerRegistry()

    @pytest.fixture
    def mock_client_with_logging(self):
        """Create a mock MCPClient with set_logging_level method."""
        client = MagicMock()
        client.set_logging_level = AsyncMock(return_value=True)
        return client

    def test_set_server_logging_level_method_exists(self, registry):
        """Test that set_server_logging_level method exists.

        RED Test: Method should exist but doesn't yet.
        """
        assert hasattr(registry, "set_server_logging_level")

    async def test_set_server_logging_level_calls_client(self, registry, mock_client_with_logging):
        """Test that set_server_logging_level calls client method."""
        # Register the mock client
        registry._clients["test-server"] = mock_client_with_logging

        # Set logging level
        result = await registry.set_server_logging_level("test-server", "debug")

        # Verify the client method was called
        assert result is True
        mock_client_with_logging.set_logging_level.assert_called_once_with("debug")

    async def test_set_server_logging_level_returns_false_for_unregistered(self, registry):
        """Test that set_server_logging_level returns False for unregistered server."""
        result = await registry.set_server_logging_level("nonexistent", "debug")
        assert result is False

    async def test_set_server_logging_level_handles_exception(self, registry, mock_client_with_logging):
        """Test that set_server_logging_level handles exceptions."""
        # Configure to raise exception
        mock_client_with_logging.set_logging_level.side_effect = RuntimeError("Failed")

        # Register the mock client
        registry._clients["test-server"] = mock_client_with_logging

        # Should not raise, return False
        result = await registry.set_server_logging_level("test-server", "debug")
        assert result is False

    async def test_set_server_logging_level_validates_level(self, registry, mock_client_with_logging):
        """Test that set_server_logging_level validates logging level."""
        # Register the mock client
        registry._clients["test-server"] = mock_client_with_logging

        # Valid levels should work
        for level in ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]:
            mock_client_with_logging.set_logging_level.reset_mock()
            result = await registry.set_server_logging_level("test-server", level)
            assert result is True
            mock_client_with_logging.set_logging_level.assert_called_once_with(level)

    async def test_set_server_logging_level_rejects_invalid_level(self, registry, mock_client_with_logging):
        """Test that set_server_logging_level rejects invalid level."""
        # Register the mock client
        registry._clients["test-server"] = mock_client_with_logging

        # Invalid level should return False without calling client
        result = await registry.set_server_logging_level("test-server", "invalid_level")
        assert result is False
        mock_client_with_logging.set_logging_level.assert_not_called()


@pytest.mark.unit
class TestMCPServerRegistryRootsConfiguration:
    """Tests for roots configuration in MCPServerRegistry.

    Priority 1: Roots Configuration Integration
    - Add methods to manage roots for servers
    - Roots allow servers to know about client's accessible directories
    """

    @pytest.fixture
    def registry(self):
        """Create a registry instance for testing."""
        return MCPServerRegistry()

    @pytest.fixture
    def mock_client_with_roots(self):
        """Create a mock MCPClient with roots methods."""
        client = MagicMock()
        client.list_roots = AsyncMock(return_value=[])
        client.send_roots_list_changed = AsyncMock(return_value=True)
        return client

    def test_add_root_method_exists(self, registry):
        """Test that add_root method exists."""
        assert hasattr(registry, "add_root")

    def test_remove_root_method_exists(self, registry):
        """Test that remove_root method exists."""
        assert hasattr(registry, "remove_root")

    def test_get_roots_method_exists(self, registry):
        """Test that get_roots method exists."""
        assert hasattr(registry, "get_roots")

    async def test_add_root_stores_root(self, registry):
        """Test that add_root stores root configuration."""
        await registry.add_root("file:///workspace", "Workspace directory")

        roots = registry.get_roots()
        assert len(roots) == 1
        assert roots[0]["uri"] == "file:///workspace"
        assert roots[0]["name"] == "Workspace directory"

    async def test_add_multiple_roots(self, registry):
        """Test adding multiple roots."""
        await registry.add_root("file:///workspace", "Workspace")
        await registry.add_root("file:///home/user", "Home")

        roots = registry.get_roots()
        assert len(roots) == 2

    async def test_remove_root(self, registry):
        """Test removing a root."""
        await registry.add_root("file:///workspace", "Workspace")
        await registry.add_root("file:///home", "Home")

        await registry.remove_root("file:///workspace")

        roots = registry.get_roots()
        assert len(roots) == 1
        assert roots[0]["uri"] == "file:///home"

    async def test_remove_nonexistent_root_silently_succeeds(self, registry):
        """Test that removing a nonexistent root succeeds silently."""
        # Should not raise
        await registry.remove_root("file:///nonexistent")

    async def test_notify_roots_list_changed(self, registry, mock_client_with_roots):
        """Test notifying servers about roots list change."""
        # Register the mock client
        registry._clients["test-server"] = mock_client_with_roots

        # Add a root and notify
        await registry.add_root("file:///workspace", "Workspace")
        await registry.notify_roots_list_changed()

        # Verify notification was sent
        mock_client_with_roots.send_roots_list_changed.assert_called_once()

    async def test_notify_roots_list_changed_to_all_servers(self, registry, mock_client_with_roots):
        """Test notifying all registered servers about roots change."""
        # Register multiple clients
        client1 = MagicMock()
        client1.send_roots_list_changed = AsyncMock(return_value=True)
        client2 = MagicMock()
        client2.send_roots_list_changed = AsyncMock(return_value=True)

        registry._clients["server1"] = client1
        registry._clients["server2"] = client2

        # Notify all
        await registry.notify_roots_list_changed()

        # Both should be notified
        client1.send_roots_list_changed.assert_called_once()
        client2.send_roots_list_changed.assert_called_once()
