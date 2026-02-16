"""Tests for MCPServerManager MCP protocol methods.

Tests for the following MCP protocol methods:
- ping: Health check for MCP servers
- resources/templates/list: List resource templates
- prompts/list: List available prompts
- prompts/get: Get a specific prompt
- logging/setLevel: Set logging level on servers
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import asyncio

from src.mcp_manager.manager import MCPServerManager
from src.mcp_manager.process_tracker import ServerStatus, ManagedServer


@pytest.fixture
def manager():
    """Create an MCPServerManager instance for testing."""
    return MCPServerManager(workspace_dir="/test/workspace")


@pytest.fixture
def mock_running_server():
    """Create a mock running server."""
    server = MagicMock(spec=ManagedServer)
    server.name = "test-server"
    server.status = ServerStatus.RUNNING
    server.server_type = "stdio"
    server.process = MagicMock()
    server.process.returncode = None
    return server


class TestPing:
    """Tests for the ping method."""

    @pytest.mark.asyncio
    async def test_ping_stdio_server_success(self, manager, mock_running_server):
        """ping should return True for a healthy stdio server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        # Mock the _send_request method to return success
        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}  # ping returns empty result

            # Act
            result = await manager.ping("test-server")

            # Assert
            assert result is True
            mock_send.assert_called_once_with("test-server", "ping")

    @pytest.mark.asyncio
    async def test_ping_nonexistent_server(self, manager):
        """ping should return False for a nonexistent server."""
        # Act
        result = await manager.ping("nonexistent-server")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_ping_stopped_server(self, manager):
        """ping should return False for a stopped server."""
        # Arrange
        server = MagicMock(spec=ManagedServer)
        server.name = "stopped-server"
        server.status = ServerStatus.STOPPED
        manager._tracker._servers["stopped-server"] = server

        # Act
        result = await manager.ping("stopped-server")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_ping_server_error(self, manager, mock_running_server):
        """ping should return False when server returns an error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        # Mock the _send_request method to raise an exception
        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = TimeoutError("Request timed out")

            # Act
            result = await manager.ping("test-server")

            # Assert
            assert result is False

    @pytest.mark.asyncio
    async def test_ping_websocket_server_success(self, manager):
        """ping should work for WebSocket servers."""
        # Arrange
        server = MagicMock(spec=ManagedServer)
        server.name = "ws-server"
        server.status = ServerStatus.RUNNING
        server.server_type = "websocket"
        manager._tracker._servers["ws-server"] = server

        # Mock WebSocket connection
        mock_ws_conn = MagicMock()
        mock_ws_conn._ws = MagicMock()
        manager._ws_connections["ws-server"] = mock_ws_conn

        # _send_request routes to _send_ws_request for websocket servers
        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}

            # Act
            result = await manager.ping("ws-server")

            # Assert
            assert result is True
            mock_send.assert_called_once_with("ws-server", "ping")


class TestListResourceTemplates:
    """Tests for the list_resource_templates method."""

    @pytest.mark.asyncio
    async def test_list_resource_templates_success(self, manager, mock_running_server):
        """list_resource_templates should return templates from server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        expected_templates = [
            {
                "uriTemplate": "file:///logs/{name}.log",
                "name": "Log Files",
                "description": "Access log files by name",
                "mimeType": "text/plain",
            }
        ]

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"resourceTemplates": expected_templates}

            # Act
            result = await manager.list_resource_templates("test-server")

            # Assert
            assert result == expected_templates
            mock_send.assert_called_once_with(
                "test-server", "resources/templates/list"
            )

    @pytest.mark.asyncio
    async def test_list_resource_templates_empty(self, manager, mock_running_server):
        """list_resource_templates should return empty list when no templates."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"resourceTemplates": []}

            # Act
            result = await manager.list_resource_templates("test-server")

            # Assert
            assert result == []

    @pytest.mark.asyncio
    async def test_list_resource_templates_nonexistent_server(self, manager):
        """list_resource_templates should return empty list for nonexistent server."""
        # Act
        result = await manager.list_resource_templates("nonexistent-server")

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_list_resource_templates_error(self, manager, mock_running_server):
        """list_resource_templates should return empty list on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.list_resource_templates("test-server")

            # Assert
            assert result == []


class TestListPrompts:
    """Tests for the list_prompts method."""

    @pytest.mark.asyncio
    async def test_list_prompts_success(self, manager, mock_running_server):
        """list_prompts should return prompts from server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        expected_prompts = [
            {
                "name": "code-review",
                "description": "Review code for best practices",
                "arguments": [
                    {"name": "code", "description": "Code to review", "required": True}
                ],
            }
        ]

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"prompts": expected_prompts}

            # Act
            result = await manager.list_prompts("test-server")

            # Assert
            assert result == expected_prompts
            mock_send.assert_called_once_with("test-server", "prompts/list")

    @pytest.mark.asyncio
    async def test_list_prompts_empty(self, manager, mock_running_server):
        """list_prompts should return empty list when no prompts."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"prompts": []}

            # Act
            result = await manager.list_prompts("test-server")

            # Assert
            assert result == []

    @pytest.mark.asyncio
    async def test_list_prompts_nonexistent_server(self, manager):
        """list_prompts should return empty list for nonexistent server."""
        # Act
        result = await manager.list_prompts("nonexistent-server")

        # Assert
        assert result == []

    @pytest.mark.asyncio
    async def test_list_prompts_error(self, manager, mock_running_server):
        """list_prompts should return empty list on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.list_prompts("test-server")

            # Assert
            assert result == []


class TestGetPrompt:
    """Tests for the get_prompt method."""

    @pytest.mark.asyncio
    async def test_get_prompt_success(self, manager, mock_running_server):
        """get_prompt should return prompt content from server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        expected_response = {
            "description": "Review the provided code",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": "Please review this code:"},
                }
            ],
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = expected_response

            # Act
            result = await manager.get_prompt(
                "test-server", "code-review", {"code": "print('hello')"}
            )

            # Assert
            assert result == expected_response
            mock_send.assert_called_once_with(
                "test-server",
                "prompts/get",
                {"name": "code-review", "arguments": {"code": "print('hello')"}},
            )

    @pytest.mark.asyncio
    async def test_get_prompt_no_arguments(self, manager, mock_running_server):
        """get_prompt should work without arguments."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        expected_response = {
            "description": "A simple greeting prompt",
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hello!"}}],
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = expected_response

            # Act
            result = await manager.get_prompt("test-server", "greeting")

            # Assert
            assert result == expected_response
            mock_send.assert_called_once_with(
                "test-server",
                "prompts/get",
                {"name": "greeting", "arguments": {}},
            )

    @pytest.mark.asyncio
    async def test_get_prompt_nonexistent_server(self, manager):
        """get_prompt should return None for nonexistent server."""
        # Act
        result = await manager.get_prompt("nonexistent-server", "test-prompt")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_get_prompt_error(self, manager, mock_running_server):
        """get_prompt should return None on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.get_prompt("test-server", "test-prompt")

            # Assert
            assert result is None


class TestSetLogLevel:
    """Tests for the set_log_level method."""

    @pytest.mark.asyncio
    async def test_set_log_level_success(self, manager, mock_running_server):
        """set_log_level should successfully set log level on server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_notification", new_callable=AsyncMock
        ) as mock_send:
            # Act
            result = await manager.set_log_level("test-server", "debug")

            # Assert
            assert result is True
            mock_send.assert_called_once_with(
                "test-server", "logging/setLevel", {"level": "debug"}
            )

    @pytest.mark.asyncio
    async def test_set_log_level_various_levels(self, manager, mock_running_server):
        """set_log_level should support all standard log levels."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        valid_levels = ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]

        for level in valid_levels:
            with patch.object(
                manager, "_send_notification", new_callable=AsyncMock
            ) as mock_send:
                # Act
                result = await manager.set_log_level("test-server", level)

                # Assert
                assert result is True
                mock_send.assert_called_once_with(
                    "test-server", "logging/setLevel", {"level": level}
                )

    @pytest.mark.asyncio
    async def test_set_log_level_nonexistent_server(self, manager):
        """set_log_level should return False for nonexistent server."""
        # Act
        result = await manager.set_log_level("nonexistent-server", "info")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_set_log_level_stopped_server(self, manager):
        """set_log_level should return False for stopped server."""
        # Arrange
        server = MagicMock(spec=ManagedServer)
        server.name = "stopped-server"
        server.status = ServerStatus.STOPPED
        manager._tracker._servers["stopped-server"] = server

        # Act
        result = await manager.set_log_level("stopped-server", "info")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_set_log_level_error(self, manager, mock_running_server):
        """set_log_level should return False on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_notification", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.set_log_level("test-server", "debug")

            # Assert
            assert result is False


class TestSubscribeResource:
    """Tests for the subscribe_resource method."""

    @pytest.mark.asyncio
    async def test_subscribe_resource_success(self, manager, mock_running_server):
        """subscribe_resource should return subscription ID on success."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        expected_subscription_id = "sub-123-abc"

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"subscriptionId": expected_subscription_id}

            # Act
            result = await manager.subscribe_resource("test-server", "file:///logs/app.log")

            # Assert
            assert result == expected_subscription_id
            mock_send.assert_called_once_with(
                "test-server",
                "resources/subscribe",
                {"uri": "file:///logs/app.log"},
            )

    @pytest.mark.asyncio
    async def test_subscribe_resource_tracks_subscription(self, manager, mock_running_server):
        """subscribe_resource should track subscription internally."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        subscription_id = "sub-456-def"
        uri = "file:///config/settings.json"

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {"subscriptionId": subscription_id}

            # Act
            result = await manager.subscribe_resource("test-server", uri)

            # Assert
            assert result == subscription_id
            # Check internal tracking
            assert "test-server" in manager._subscriptions
            assert subscription_id in manager._subscriptions["test-server"]
            assert manager._subscriptions["test-server"][subscription_id] == uri

    @pytest.mark.asyncio
    async def test_subscribe_resource_nonexistent_server(self, manager):
        """subscribe_resource should return None for nonexistent server."""
        # Act
        result = await manager.subscribe_resource("nonexistent-server", "file:///test.txt")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_resource_stopped_server(self, manager):
        """subscribe_resource should return None for stopped server."""
        # Arrange
        server = MagicMock(spec=ManagedServer)
        server.name = "stopped-server"
        server.status = ServerStatus.STOPPED
        manager._tracker._servers["stopped-server"] = server

        # Act
        result = await manager.subscribe_resource("stopped-server", "file:///test.txt")

        # Assert
        assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_resource_error(self, manager, mock_running_server):
        """subscribe_resource should return None on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.subscribe_resource("test-server", "file:///test.txt")

            # Assert
            assert result is None

    @pytest.mark.asyncio
    async def test_subscribe_resource_no_subscription_id_in_response(self, manager, mock_running_server):
        """subscribe_resource should return None if response lacks subscriptionId."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}  # Missing subscriptionId

            # Act
            result = await manager.subscribe_resource("test-server", "file:///test.txt")

            # Assert
            assert result is None


class TestUnsubscribeResource:
    """Tests for the unsubscribe_resource method."""

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_success(self, manager, mock_running_server):
        """unsubscribe_resource should return True on success."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {
            "test-server": {"sub-123": "file:///logs/app.log"}
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}

            # Act
            result = await manager.unsubscribe_resource("test-server", "sub-123")

            # Assert
            assert result is True
            mock_send.assert_called_once_with(
                "test-server",
                "resources/unsubscribe",
                {"subscriptionId": "sub-123"},
            )
            # Check subscription was removed
            assert "sub-123" not in manager._subscriptions.get("test-server", {})

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_removes_from_tracking(self, manager, mock_running_server):
        """unsubscribe_resource should remove subscription from internal tracking."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {
            "test-server": {
                "sub-1": "file:///a.txt",
                "sub-2": "file:///b.txt",
            }
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}

            # Act
            result = await manager.unsubscribe_resource("test-server", "sub-1")

            # Assert
            assert result is True
            assert "sub-1" not in manager._subscriptions["test-server"]
            assert "sub-2" in manager._subscriptions["test-server"]

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_nonexistent_server(self, manager):
        """unsubscribe_resource should return False for nonexistent server."""
        # Act
        result = await manager.unsubscribe_resource("nonexistent-server", "sub-123")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_stopped_server(self, manager):
        """unsubscribe_resource should return False for stopped server."""
        # Arrange
        server = MagicMock(spec=ManagedServer)
        server.name = "stopped-server"
        server.status = ServerStatus.STOPPED
        manager._tracker._servers["stopped-server"] = server

        # Act
        result = await manager.unsubscribe_resource("stopped-server", "sub-123")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_nonexistent_subscription(self, manager, mock_running_server):
        """unsubscribe_resource should return False for nonexistent subscription."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {"test-server": {}}

        # Act
        result = await manager.unsubscribe_resource("test-server", "nonexistent-sub")

        # Assert
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_error(self, manager, mock_running_server):
        """unsubscribe_resource should return False on error."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {
            "test-server": {"sub-123": "file:///test.txt"}
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.side_effect = Exception("Connection error")

            # Act
            result = await manager.unsubscribe_resource("test-server", "sub-123")

            # Assert
            assert result is False
            # Subscription should still be tracked (cleanup only on success)
            assert "sub-123" in manager._subscriptions["test-server"]

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_cleans_empty_server_entry(self, manager, mock_running_server):
        """unsubscribe_resource should remove server entry when no subscriptions remain."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {
            "test-server": {"sub-last": "file:///last.txt"}
        }

        with patch.object(
            manager, "_send_request", new_callable=AsyncMock
        ) as mock_send:
            mock_send.return_value = {}

            # Act
            result = await manager.unsubscribe_resource("test-server", "sub-last")

            # Assert
            assert result is True
            assert "test-server" not in manager._subscriptions


class TestGetActiveSubscriptions:
    """Tests for the get_active_subscriptions method."""

    @pytest.mark.asyncio
    async def test_get_active_subscriptions_returns_all(self, manager):
        """get_active_subscriptions should return all subscriptions for a server."""
        # Arrange
        manager._subscriptions = {
            "test-server": {
                "sub-1": "file:///a.txt",
                "sub-2": "file:///b.txt",
            }
        }

        # Act
        result = manager.get_active_subscriptions("test-server")

        # Assert
        assert result == {
            "sub-1": "file:///a.txt",
            "sub-2": "file:///b.txt",
        }

    @pytest.mark.asyncio
    async def test_get_active_subscriptions_empty(self, manager):
        """get_active_subscriptions should return empty dict for server with no subscriptions."""
        # Arrange
        manager._subscriptions = {}

        # Act
        result = manager.get_active_subscriptions("test-server")

        # Assert
        assert result == {}

    @pytest.mark.asyncio
    async def test_get_active_subscriptions_returns_copy(self, manager):
        """get_active_subscriptions should return a copy, not the original dict."""
        # Arrange
        manager._subscriptions = {
            "test-server": {"sub-1": "file:///a.txt"}
        }

        # Act
        result = manager.get_active_subscriptions("test-server")
        result["sub-new"] = "file:///new.txt"

        # Assert
        assert "sub-new" not in manager._subscriptions["test-server"]


class TestSubscriptionCleanup:
    """Tests for subscription cleanup on server stop."""

    @pytest.mark.asyncio
    async def test_stop_server_cleans_subscriptions(self, manager, mock_running_server):
        """stop_server should clean up subscriptions for the server."""
        # Arrange
        manager._tracker._servers["test-server"] = mock_running_server
        manager._subscriptions = {
            "test-server": {
                "sub-1": "file:///a.txt",
                "sub-2": "file:///b.txt",
            },
            "other-server": {
                "sub-3": "file:///c.txt",
            }
        }
        manager._tools_cache["test-server"] = []

        # Mock the tracker stop
        with patch.object(
            manager._tracker, "stop_server", new_callable=AsyncMock
        ) as mock_stop:
            mock_stop.return_value = True

            # Act
            await manager.stop_server("test-server")

            # Assert
            assert "test-server" not in manager._subscriptions
            assert "other-server" in manager._subscriptions  # Other servers unaffected

    @pytest.mark.asyncio
    async def test_shutdown_cleans_all_subscriptions(self, manager):
        """shutdown should clean up all subscriptions."""
        # Arrange
        manager._subscriptions = {
            "server-1": {"sub-1": "file:///a.txt"},
            "server-2": {"sub-2": "file:///b.txt"},
        }

        # Act
        with patch.object(manager._tracker, "stop_all", new_callable=AsyncMock):
            await manager.shutdown()

        # Assert
        assert manager._subscriptions == {}
