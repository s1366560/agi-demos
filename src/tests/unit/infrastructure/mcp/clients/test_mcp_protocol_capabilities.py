"""Unit tests for MCP protocol capabilities.

Tests for missing MCP protocol features:
- Ping mechanism
- Prompts API
- Resource subscriptions
- Progress tracking
- Logging
- Sampling (Phase 2)
- Elicitation (Phase 2)
- Roots (Phase 2)
- Cancellation
- Completion

Reference: https://modelcontextprotocol.io/specification/2025-11-25
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ============================================================================
# Edge Case Tests for Improved Coverage
# ============================================================================


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_list_prompts_with_server_error(self):
        """Test list_prompts handles server errors gracefully."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = RuntimeError("Server error")

            prompts = await client.list_prompts()

            # Should return empty list on error
            assert prompts == []

    @pytest.mark.asyncio
    async def test_get_prompt_with_none_response(self):
        """Test get_prompt handles None response."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = None

            prompt = await client.get_prompt("test", {})

            assert prompt is None

    @pytest.mark.asyncio
    async def test_subscribe_resource_with_connection_error(self):
        """Test subscribe_resource handles connection errors."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = ConnectionError("Connection lost")

            result = await client.subscribe_resource("file:///test.txt")

            assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_resource_with_exception(self):
        """Test unsubscribe_resource handles exceptions."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Unexpected error")

            result = await client.unsubscribe_resource("file:///test.txt")

            assert result is False

    @pytest.mark.asyncio
    async def test_ping_with_exception(self):
        """Test ping handles unexpected exceptions."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Unexpected error")

            result = await client.ping()

            assert result is False

    @pytest.mark.asyncio
    async def test_set_logging_level_with_exception(self):
        """Test set_logging_level handles exceptions."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Unexpected error")

            result = await client.set_logging_level("debug")

            assert result is False

    @pytest.mark.asyncio
    async def test_notification_handler_not_set(self):
        """Test notification handling when no handler is set."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Don't set any handlers - should not raise error
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/resources/updated",
            "params": {"uri": "file:///test.txt"},
        }

        # Should handle gracefully without handler
        await client._handle_message(notification)

    @pytest.mark.asyncio
    async def test_get_prompt_with_empty_arguments(self):
        """Test get_prompt with empty arguments dict."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        mock_response = {
            "description": "Test prompt",
            "messages": [],
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            prompt = await client.get_prompt("test", {})

            # Verify empty dict was passed
            call_args = mock_send.call_args
            assert call_args[0][1]["arguments"] == {}
            assert prompt["description"] == "Test prompt"

    @pytest.mark.asyncio
    async def test_get_prompt_with_none_arguments(self):
        """Test get_prompt with None arguments."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        mock_response = {
            "description": "Test prompt",
            "messages": [],
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            _prompt = await client.get_prompt("test", None)

            # Verify empty dict was used
            call_args = mock_send.call_args
            assert call_args[0][1]["arguments"] == {}

    @pytest.mark.asyncio
    async def test_multiple_notification_handlers(self):
        """Test that different notification types call different handlers."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        resource_updates = []
        progress_updates = []

        async def on_resource(params):
            resource_updates.append(params)

        async def on_progress(params):
            progress_updates.append(params)

        client.on_resource_updated = on_resource
        client.on_progress = on_progress

        # Send resource update
        await client._handle_message(
            {
                "jsonrpc": "2.0",
                "method": "notifications/resources/updated",
                "params": {"uri": "file:///test.txt"},
            }
        )

        # Send progress update
        await client._handle_message(
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {"progress": 50},
            }
        )

        # Verify correct handlers called
        assert len(resource_updates) == 1
        assert len(progress_updates) == 1
        assert resource_updates[0]["uri"] == "file:///test.txt"
        assert progress_updates[0]["progress"] == 50

    @pytest.mark.asyncio
    async def test_custom_timeout_for_ping(self):
        """Test ping with custom timeout."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}

            result = await client.ping(timeout=120)

            # Verify custom timeout was used
            call_args = mock_send.call_args
            assert call_args[1]["timeout"] == 120
            assert result is True

    @pytest.mark.asyncio
    async def test_custom_timeout_for_subscribe(self):
        """Test subscribe_resource with custom timeout."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}

            result = await client.subscribe_resource("file:///test.txt", timeout=45)

            call_args = mock_send.call_args
            assert call_args[1]["timeout"] == 45
            assert result is True


# ============================================================================
# Ping Mechanism Tests (Phase 1 - Highest Priority)
# ============================================================================


class TestPingMechanism:
    """Tests for MCP ping/pong health check mechanism."""

    @pytest.mark.asyncio
    async def test_websocket_client_ping_success(self):
        """Test successful ping to MCP server via WebSocket."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()

        client._ws = mock_ws

        # Mock _send_request to return success
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}  # Ping returns empty result

            result = await client.ping()

            # Verify ping was sent with correct method
            mock_send.assert_called_once_with("ping", {}, timeout=client.timeout)
            assert result is True

    @pytest.mark.asyncio
    async def test_websocket_client_ping_timeout(self):
        """Test ping timeout handling."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock _send_request to return None (timeout)
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = None

            result = await client.ping()

            assert result is False

    @pytest.mark.asyncio
    async def test_websocket_client_ping_not_connected(self):
        """Test ping when not connected raises error."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # No WebSocket connection
        result = await client.ping()

        assert result is False

    @pytest.mark.asyncio
    async def test_subprocess_client_ping_success(self):
        """Test successful ping to MCP server via subprocess."""
        from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

        client = MCPSubprocessClient(command="test")

        # Mock _send_request to return success
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"result": {}}

            result = await client.ping()

            # Verify ping was sent with correct method
            mock_send.assert_called_once_with("ping", {}, timeout=client.timeout)
            assert result is True

    @pytest.mark.asyncio
    async def test_subprocess_client_ping_timeout(self):
        """Test ping timeout handling for subprocess client."""
        from src.infrastructure.mcp.clients.subprocess_client import MCPSubprocessClient

        client = MCPSubprocessClient(command="test")

        # Mock _send_request to return None (timeout)
        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = None

            result = await client.ping()

            assert result is False


# ============================================================================
# Prompts API Tests (Phase 1)
# ============================================================================


class TestPromptsAPI:
    """Tests for MCP prompts API."""

    @pytest.mark.asyncio
    async def test_list_prompts_success(self):
        """Test listing available prompts."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        mock_response = {
            "prompts": [
                {
                    "name": "code_review",
                    "description": "Review code for quality issues",
                    "arguments": [
                        {
                            "name": "code",
                            "description": "Code to review",
                            "required": True,
                        }
                    ],
                }
            ]
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            prompts = await client.list_prompts()

            mock_send.assert_called_once_with("prompts/list", {}, timeout=client.timeout)
            assert len(prompts) == 1
            assert prompts[0]["name"] == "code_review"

    @pytest.mark.asyncio
    async def test_get_prompt_success(self):
        """Test getting a specific prompt template."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        mock_response = {
            "description": "Review code for quality issues",
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "text", "text": "Review this code: {code}"},
                }
            ],
        }

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = mock_response

            prompt = await client.get_prompt("code_review", {"code": "def foo(): pass"})

            mock_send.assert_called_once_with(
                "prompts/get",
                {"name": "code_review", "arguments": {"code": "def foo(): pass"}},
                timeout=client.timeout,
            )
            assert prompt["description"] == "Review code for quality issues"

    @pytest.mark.asyncio
    async def test_list_prompts_empty(self):
        """Test listing prompts when none available."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"prompts": []}

            prompts = await client.list_prompts()

            assert len(prompts) == 0


# ============================================================================
# Resource Subscriptions Tests (Phase 1)
# ============================================================================


class TestResourceSubscriptions:
    """Tests for MCP resource subscription mechanism."""

    @pytest.mark.asyncio
    async def test_subscribe_to_resource(self):
        """Test subscribing to resource updates."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}  # Success

            result = await client.subscribe_resource("file:///path/to/file.txt")

            mock_send.assert_called_once_with(
                "resources/subscribe",
                {"uri": "file:///path/to/file.txt"},
                timeout=client.timeout,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_unsubscribe_from_resource(self):
        """Test unsubscribing from resource updates."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}  # Success

            result = await client.unsubscribe_resource("file:///path/to/file.txt")

            mock_send.assert_called_once_with(
                "resources/unsubscribe",
                {"uri": "file:///path/to/file.txt"},
                timeout=client.timeout,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_resource_update_notification_handler(self):
        """Test handling resource update notifications from server."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track notification handling
        notifications_received = []

        async def on_resource_updated(params):
            notifications_received.append(params)

        # Register handler
        client.on_resource_updated = on_resource_updated

        # Simulate receiving notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/resources/updated",
            "params": {"uri": "file:///path/to/file.txt"},
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(notifications_received) == 1
        assert notifications_received[0]["uri"] == "file:///path/to/file.txt"

    @pytest.mark.asyncio
    async def test_resource_list_changed_notification(self):
        """Test handling resource list changed notifications."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track notification handling
        notifications_received = []

        async def on_resource_list_changed(params):
            notifications_received.append(params)

        # Register handler
        client.on_resource_list_changed = on_resource_list_changed

        # Simulate receiving notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/resources/list_changed",
            "params": {},
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(notifications_received) == 1


# ============================================================================
# Progress Tracking Tests (Phase 1)
# ============================================================================


class TestProgressTracking:
    """Tests for MCP progress notifications."""

    @pytest.mark.asyncio
    async def test_progress_notification_handler(self):
        """Test handling progress notifications from server."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track progress updates
        progress_updates = []

        async def on_progress(params):
            progress_updates.append(params)

        # Register handler
        client.on_progress = on_progress

        # Simulate receiving progress notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/progress",
            "params": {
                "progressToken": "task-123",
                "progress": 50,
                "total": 100,
            },
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(progress_updates) == 1
        assert progress_updates[0]["progress"] == 50
        assert progress_updates[0]["progressToken"] == "task-123"


# ============================================================================
# Logging Tests (Phase 1)
# ============================================================================


class TestLogging:
    """Tests for MCP logging level control."""

    @pytest.mark.asyncio
    async def test_set_logging_level(self):
        """Test setting server logging level."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {}  # Success

            result = await client.set_logging_level("debug")

            mock_send.assert_called_once_with(
                "logging/setLevel",
                {"level": "debug"},
                timeout=client.timeout,
            )
            assert result is True

    @pytest.mark.asyncio
    async def test_set_logging_level_invalid(self):
        """Test setting invalid logging level."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = RuntimeError("Invalid log level")

            result = await client.set_logging_level("invalid")

            assert result is False


# ============================================================================
# Cancellation Tests (Phase 2)
# ============================================================================


class TestCancellation:
    """Tests for MCP request cancellation."""

    @pytest.mark.asyncio
    async def test_cancelled_notification_handler(self):
        """Test handling cancellation notifications."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track cancellations
        cancellations = []

        async def on_cancelled(params):
            cancellations.append(params)

        # Register handler
        client.on_cancelled = on_cancelled

        # Simulate receiving cancellation notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {
                "requestId": 123,
                "reason": "User cancelled",
            },
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(cancellations) == 1
        assert cancellations[0]["requestId"] == 123


# ============================================================================
# Prompts List Changed Notification Tests
# ============================================================================


class TestPromptsListChanged:
    """Tests for prompts list changed notifications."""

    @pytest.mark.asyncio
    async def test_prompts_list_changed_notification_handler(self):
        """Test handling prompts list changed notifications."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track notifications
        notifications = []

        async def on_prompts_list_changed(params):
            notifications.append(params)

        # Register handler
        client.on_prompts_list_changed = on_prompts_list_changed

        # Simulate receiving notification
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/prompts/list_changed",
            "params": {},
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(notifications) == 1


# ============================================================================
# Sampling Tests (Phase 2)
# ============================================================================


class TestSampling:
    """Tests for MCP sampling - server-initiated LLM requests.

    Sampling allows MCP servers to request LLM completions through the client.
    The server sends a 'sampling/createMessage' request and the client responds
    with the LLM's completion.

    Reference: https://modelcontextprotocol.io/docs/concepts/sampling
    """

    @pytest.mark.asyncio
    async def test_sampling_request_handler_called(self):
        """Test that sampling request from server triggers handler."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track sampling requests
        sampling_requests = []

        async def on_sampling_request(params):
            sampling_requests.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "Sample response"},
                "model": "test-model",
                "stopReason": "endTurn",
            }

        # Register handler
        client.on_sampling_request = on_sampling_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 123,
            "method": "sampling/createMessage",
            "params": {
                "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
                "modelPreferences": {
                    "hints": [{"name": "claude"}],
                    "costPriority": 0.5,
                },
                "maxTokens": 100,
            },
        }

        await client._handle_message(request)

        # Verify handler was called with correct params
        assert len(sampling_requests) == 1
        assert sampling_requests[0]["maxTokens"] == 100

    @pytest.mark.asyncio
    async def test_sampling_request_without_handler_returns_error(self):
        """Test that sampling request without handler returns error response."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # No handler registered

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 123,
            "method": "sampling/createMessage",
            "params": {
                "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
            },
        }

        await client._handle_message(request)

        # Verify error response was sent
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 123
        assert "error" in response
        assert response["error"]["code"] == -32601  # Method not found

    @pytest.mark.asyncio
    async def test_sampling_request_handler_exception(self):
        """Test that handler exceptions are caught and returned as errors."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Handler that throws
        async def on_sampling_request(params):
            raise RuntimeError("LLM unavailable")

        client.on_sampling_request = on_sampling_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 456,
            "method": "sampling/createMessage",
            "params": {
                "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
            },
        }

        await client._handle_message(request)

        # Verify error response was sent
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["id"] == 456
        assert "error" in response
        assert "LLM unavailable" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_sampling_request_successful_response(self):
        """Test successful sampling request returns proper response."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Handler that returns valid response
        async def on_sampling_request(params):
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "Hello! How can I help?"},
                "model": "claude-3-sonnet",
                "stopReason": "endTurn",
            }

        client.on_sampling_request = on_sampling_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 789,
            "method": "sampling/createMessage",
            "params": {
                "messages": [{"role": "user", "content": {"type": "text", "text": "Hello"}}],
                "maxTokens": 50,
            },
        }

        await client._handle_message(request)

        # Verify success response was sent
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 789
        assert "result" in response
        assert response["result"]["role"] == "assistant"
        assert response["result"]["content"]["text"] == "Hello! How can I help?"


# ============================================================================
# Elicitation Tests (Phase 2)
# ============================================================================


class TestElicitation:
    """Tests for MCP elicitation - server requests info from user.

    Elicitation allows MCP servers to request additional information
    from users through the client. The server sends 'elicitation/create'
    and the client responds with user input.

    Reference: https://modelcontextprotocol.io/specification/2025-11-25
    """

    @pytest.mark.asyncio
    async def test_elicitation_request_handler_called(self):
        """Test that elicitation request from server triggers handler."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track elicitation requests
        elicitation_requests = []

        async def on_elicitation_request(params):
            elicitation_requests.append(params)
            return {"action": "accept", "content": "User provided value"}

        # Register handler
        client.on_elicitation_request = on_elicitation_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 100,
            "method": "elicitation/create",
            "params": {
                "message": "Please provide your API key",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"apiKey": {"type": "string"}},
                },
            },
        }

        await client._handle_message(request)

        # Verify handler was called
        assert len(elicitation_requests) == 1
        assert elicitation_requests[0]["message"] == "Please provide your API key"

    @pytest.mark.asyncio
    async def test_elicitation_request_without_handler_returns_error(self):
        """Test that elicitation request without handler returns error."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # No handler registered

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 101,
            "method": "elicitation/create",
            "params": {
                "message": "Please provide input",
            },
        }

        await client._handle_message(request)

        # Verify error response was sent
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["id"] == 101
        assert "error" in response
        assert response["error"]["code"] == -32601

    @pytest.mark.asyncio
    async def test_elicitation_request_user_declines(self):
        """Test elicitation when user declines to provide info."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Handler that returns decline
        async def on_elicitation_request(params):
            return {"action": "decline"}

        client.on_elicitation_request = on_elicitation_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 102,
            "method": "elicitation/create",
            "params": {"message": "Provide sensitive data"},
        }

        await client._handle_message(request)

        # Verify decline response
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["result"]["action"] == "decline"

    @pytest.mark.asyncio
    async def test_elicitation_request_user_cancels(self):
        """Test elicitation when user cancels the request."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Handler that returns cancel
        async def on_elicitation_request(params):
            return {"action": "cancel"}

        client.on_elicitation_request = on_elicitation_request

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 103,
            "method": "elicitation/create",
            "params": {"message": "Provide input"},
        }

        await client._handle_message(request)

        # Verify cancel response
        response = mock_ws.send_json.call_args[0][0]
        assert response["result"]["action"] == "cancel"


# ============================================================================
# Roots Tests (Phase 2)
# ============================================================================


class TestRoots:
    """Tests for MCP roots - client workspace boundaries.

    Roots allow servers to understand the client's workspace boundaries
    and working directories. Servers query 'roots/list' and clients
    can notify about changes via 'notifications/roots/list_changed'.

    Reference: https://modelcontextprotocol.io/specification/2025-11-25
    """

    @pytest.mark.asyncio
    async def test_roots_list_request_handler_called(self):
        """Test that roots/list request from server triggers handler."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Track roots requests
        roots_requests = []

        async def on_roots_list(params):
            roots_requests.append(params)
            return {
                "roots": [
                    {"uri": "file:///home/user/project", "name": "Project Root"},
                    {"uri": "file:///home/user/data", "name": "Data Directory"},
                ]
            }

        # Register handler
        client.on_roots_list = on_roots_list

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 200,
            "method": "roots/list",
            "params": {},
        }

        await client._handle_message(request)

        # Verify handler was called and response sent
        assert len(roots_requests) == 1
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["id"] == 200
        assert "result" in response
        assert len(response["result"]["roots"]) == 2
        assert response["result"]["roots"][0]["uri"] == "file:///home/user/project"

    @pytest.mark.asyncio
    async def test_roots_list_without_handler_returns_default(self):
        """Test roots/list without handler returns empty roots list."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # No handler registered

        # Simulate server request
        request = {
            "jsonrpc": "2.0",
            "id": 201,
            "method": "roots/list",
            "params": {},
        }

        await client._handle_message(request)

        # Verify default empty response
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["id"] == 201
        assert "result" in response
        assert response["result"]["roots"] == []

    @pytest.mark.asyncio
    async def test_roots_list_changed_notification_handler(self):
        """Test handling roots list changed notification."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Track notifications
        notifications = []

        async def on_roots_list_changed(params):
            notifications.append(params)

        # Register handler
        client.on_roots_list_changed = on_roots_list_changed

        # Simulate notification (this is CLIENT -> SERVER notification)
        # But servers can also send this if they support the capability
        notification = {
            "jsonrpc": "2.0",
            "method": "notifications/roots/list_changed",
            "params": {},
        }

        await client._handle_message(notification)

        # Verify handler was called
        assert len(notifications) == 1

    @pytest.mark.asyncio
    async def test_notify_roots_list_changed_method(self):
        """Test client can send roots list changed notification to server."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Send notification
        await client.notify_roots_list_changed()

        # Verify notification was sent
        mock_ws.send_json.assert_called_once()
        notification = mock_ws.send_json.call_args[0][0]
        assert notification["jsonrpc"] == "2.0"
        assert notification["method"] == "notifications/roots/list_changed"

    @pytest.mark.asyncio
    async def test_set_roots_method(self):
        """Test set_roots updates internal roots and notifies server."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Set roots
        roots = [
            {"uri": "file:///workspace", "name": "Workspace"},
        ]
        await client.set_roots(roots)

        # Verify internal state updated
        assert client._roots == roots

        # Verify notification sent
        mock_ws.send_json.assert_called_once()
        notification = mock_ws.send_json.call_args[0][0]
        assert notification["method"] == "notifications/roots/list_changed"


# ============================================================================
# Completion Tests (Phase 2 - Optional)
# ============================================================================


class TestCompletion:
    """Tests for MCP completion - auto-completion support.

    Completion allows servers to provide auto-completion suggestions
    for prompt arguments and resource templates.

    Reference: https://modelcontextprotocol.io/specification/2025-11-25
    """

    @pytest.mark.asyncio
    async def test_complete_method_exists(self):
        """Test that complete method exists and works."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        client._ws = mock_ws

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                "completion": {
                    "values": ["option1", "option2", "option3"],
                    "total": 3,
                    "hasMore": False,
                }
            }

            result = await client.complete(
                ref={"type": "ref/prompt", "name": "test"},
                argument={"name": "arg1", "value": "opt"},
            )

            # Verify request was sent correctly
            mock_send.assert_called_once()
            call_args = mock_send.call_args
            assert call_args[0][0] == "completion/complete"
            assert call_args[0][1]["ref"]["type"] == "ref/prompt"
            assert call_args[0][1]["argument"]["value"] == "opt"

            # Verify result
            assert result is not None
            assert result["completion"]["values"] == ["option1", "option2", "option3"]

    @pytest.mark.asyncio
    async def test_complete_for_resource_template(self):
        """Test completion for resource template references."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                "completion": {
                    "values": ["file1.txt", "file2.txt"],
                    "total": 2,
                    "hasMore": False,
                }
            }

            result = await client.complete(
                ref={"type": "ref/resource", "uri": "file:///{path}"},
                argument={"name": "path", "value": "file"},
            )

            assert result["completion"]["values"] == ["file1.txt", "file2.txt"]

    @pytest.mark.asyncio
    async def test_complete_returns_none_on_error(self):
        """Test complete returns None on error."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Server error")

            result = await client.complete(
                ref={"type": "ref/prompt", "name": "test"},
                argument={"name": "arg1", "value": "test"},
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_complete_with_context(self):
        """Test complete with context for better suggestions."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {
                "completion": {
                    "values": ["contextual_suggestion"],
                    "total": 1,
                    "hasMore": False,
                }
            }

            result = await client.complete(
                ref={"type": "ref/prompt", "name": "code_review"},
                argument={"name": "language", "value": "py"},
                context={"previousArguments": {"code": "def foo(): pass"}},
            )

            # Verify context was included in request
            call_args = mock_send.call_args
            assert "context" in call_args[0][1]
            assert result["completion"]["values"] == ["contextual_suggestion"]


# ============================================================================
# Phase 2 Edge Cases and Error Handling Tests
# ============================================================================


class TestPhase2EdgeCases:
    """Additional edge case tests for Phase 2 capabilities."""

    @pytest.mark.asyncio
    async def test_unknown_server_request_returns_error(self):
        """Test that unknown server requests return method not found error."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket for sending response
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Simulate unknown method request
        request = {
            "jsonrpc": "2.0",
            "id": 999,
            "method": "unknown/method",
            "params": {},
        }

        await client._handle_message(request)

        # Verify error response
        mock_ws.send_json.assert_called_once()
        response = mock_ws.send_json.call_args[0][0]
        assert response["error"]["code"] == -32601
        assert "Method not found" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_roots_list_handler_exception(self):
        """Test roots/list handler exception handling."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Handler that throws
        async def on_roots_list(params):
            raise RuntimeError("Failed to get roots")

        client.on_roots_list = on_roots_list

        # Simulate request
        request = {
            "jsonrpc": "2.0",
            "id": 300,
            "method": "roots/list",
            "params": {},
        }

        await client._handle_message(request)

        # Verify error response
        response = mock_ws.send_json.call_args[0][0]
        assert response["error"]["code"] == -32603
        assert "Roots list failed" in response["error"]["message"]

    @pytest.mark.asyncio
    async def test_send_response_when_ws_closed(self):
        """Test _send_response handles closed WebSocket gracefully."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock closed WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = True
        client._ws = mock_ws

        # Should not raise error
        await client._send_response(123, result={"test": "data"})

        # send_json should not be called
        mock_ws.send_json.assert_not_called()

    @pytest.mark.asyncio
    async def test_send_response_error(self):
        """Test _send_response handles send errors."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket that throws
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock(side_effect=RuntimeError("Send failed"))
        client._ws = mock_ws

        # Should not raise error
        await client._send_response(123, result={"test": "data"})

        # Verify send was attempted
        mock_ws.send_json.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_roots_stores_and_notifies(self):
        """Test set_roots updates internal state and sends notification."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        roots = [
            {"uri": "file:///workspace", "name": "Workspace"},
        ]

        await client.set_roots(roots)

        # Verify roots stored
        assert client._roots == roots

        # Verify notification sent
        mock_ws.send_json.assert_called_once()
        notification = mock_ws.send_json.call_args[0][0]
        assert notification["method"] == "notifications/roots/list_changed"

    @pytest.mark.asyncio
    async def test_roots_list_returns_internal_roots_by_default(self):
        """Test roots/list returns internally stored roots when no handler."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Set internal roots
        client._roots = [{"uri": "file:///data", "name": "Data"}]

        # Simulate request (no handler set)
        request = {
            "jsonrpc": "2.0",
            "id": 400,
            "method": "roots/list",
            "params": {},
        }

        await client._handle_message(request)

        # Verify response contains internal roots
        response = mock_ws.send_json.call_args[0][0]
        assert response["result"]["roots"] == [{"uri": "file:///data", "name": "Data"}]

    @pytest.mark.asyncio
    async def test_complete_with_custom_timeout(self):
        """Test complete method with custom timeout."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.return_value = {"completion": {"values": []}}

            await client.complete(
                ref={"type": "ref/prompt", "name": "test"},
                argument={"name": "arg", "value": "val"},
                timeout=120,
            )

            # Verify timeout was passed
            call_args = mock_send.call_args
            assert call_args[1]["timeout"] == 120

    @pytest.mark.asyncio
    async def test_notify_roots_list_changed_when_disconnected(self):
        """Test notify_roots_list_changed handles disconnected state."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # No WebSocket
        client._ws = None

        # Should not raise error
        await client.notify_roots_list_changed()

    @pytest.mark.asyncio
    async def test_handle_server_request_internal_exception(self):
        """Test _handle_server_request catches internal exceptions."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        # Mock _handle_sampling_request to throw
        async def failing_handler(request_id, params):
            raise RuntimeError("Internal handler error")

        client._handle_sampling_request = failing_handler

        # This should still return a proper error response
        await client._handle_server_request(123, "sampling/createMessage", {})

        # The exception should be caught and error sent
        response = mock_ws.send_json.call_args[0][0]
        assert "error" in response
        assert response["error"]["code"] == -32603

    @pytest.mark.asyncio
    async def test_complete_returns_none_on_exception(self):
        """Test complete returns None when _send_request throws."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        with patch.object(client, "_send_request", new_callable=AsyncMock) as mock_send:
            mock_send.side_effect = Exception("Network error")

            result = await client.complete(
                ref={"type": "ref/prompt", "name": "test"},
                argument={"name": "arg", "value": "val"},
            )

            assert result is None

    @pytest.mark.asyncio
    async def test_sampling_handler_called_with_full_params(self):
        """Test sampling handler receives all params correctly."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        received_params = []

        async def on_sampling(params):
            received_params.append(params)
            return {
                "role": "assistant",
                "content": {"type": "text", "text": "Response"},
                "model": "test-model",
                "stopReason": "endTurn",
            }

        client.on_sampling_request = on_sampling

        full_params = {
            "messages": [{"role": "user", "content": {"type": "text", "text": "Hi"}}],
            "modelPreferences": {
                "hints": [{"name": "claude-3"}],
                "costPriority": 0.8,
                "speedPriority": 0.5,
                "intelligencePriority": 0.9,
            },
            "systemPrompt": "You are helpful",
            "includeContext": "thisServer",
            "maxTokens": 2000,
            "temperature": 0.7,
        }

        request = {
            "jsonrpc": "2.0",
            "id": 500,
            "method": "sampling/createMessage",
            "params": full_params,
        }

        await client._handle_message(request)

        # Verify all params passed to handler
        assert received_params[0] == full_params
        assert received_params[0]["maxTokens"] == 2000
        assert received_params[0]["temperature"] == 0.7

    @pytest.mark.asyncio
    async def test_elicitation_handler_receives_schema(self):
        """Test elicitation handler receives requestedSchema."""
        from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

        client = MCPWebSocketClient(url="ws://localhost:8765")

        # Mock WebSocket
        mock_ws = MagicMock()
        mock_ws.closed = False
        mock_ws.send_json = AsyncMock()
        client._ws = mock_ws

        received_params = []

        async def on_elicitation(params):
            received_params.append(params)
            return {"action": "accept", "content": {"name": "test"}}

        client.on_elicitation_request = on_elicitation

        request = {
            "jsonrpc": "2.0",
            "id": 600,
            "method": "elicitation/create",
            "params": {
                "message": "Enter your name",
                "requestedSchema": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        }

        await client._handle_message(request)

        # Verify schema was passed
        assert "requestedSchema" in received_params[0]
        assert received_params[0]["requestedSchema"]["type"] == "object"
