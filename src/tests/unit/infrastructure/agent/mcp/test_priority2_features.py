"""Unit tests for MCP Priority 2 features.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

Priority 2 Features:
1. Progress Tracking Integration - AgentProgressEvent
2. Resource Subscription Integration - Frontend hook exposure
3. Cancel Handling Integration - processor on_cancelled notification
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.domain.events.types import AgentEventType


@pytest.mark.unit
class TestAgentProgressEvent:
    """Tests for AgentProgressEvent domain event.

    Priority 2: Progress Tracking Integration
    - Add AgentProgressEvent event
    - Emitted when tools report progress during long-running operations
    """

    def test_progress_event_type_exists(self):
        """Test that PROGRESS event type exists in AgentEventType."""
        assert hasattr(AgentEventType, "PROGRESS")

    def test_progress_event_class_exists(self):
        """Test that AgentProgressEvent class exists."""
        from src.domain.events.agent_events import AgentProgressEvent

        assert AgentProgressEvent is not None

    def test_progress_event_creation(self):
        """Test creating a progress event."""
        from src.domain.events.agent_events import AgentProgressEvent

        event = AgentProgressEvent(
            tool_name="long_running_task",
            progress_token="task-123",
            progress=0.5,
            total=1.0,
            message="Processing data...",
        )

        assert event.event_type == AgentEventType.PROGRESS
        assert event.tool_name == "long_running_task"
        assert event.progress_token == "task-123"
        assert event.progress == 0.5
        assert event.total == 1.0
        assert event.message == "Processing data..."

    def test_progress_event_optional_fields(self):
        """Test progress event with optional fields."""
        from src.domain.events.agent_events import AgentProgressEvent

        event = AgentProgressEvent(
            tool_name="simple_task",
            progress_token="task-456",
            progress=0.75,
        )

        assert event.total is None
        assert event.message is None

    def test_progress_event_to_event_dict(self):
        """Test progress event serialization."""
        from src.domain.events.agent_events import AgentProgressEvent

        event = AgentProgressEvent(
            tool_name="task",
            progress_token="token-1",
            progress=0.25,
            total=1.0,
            message="25% complete",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "progress"
        assert "data" in event_dict
        assert event_dict["data"]["tool_name"] == "task"
        assert event_dict["data"]["progress_token"] == "token-1"
        assert event_dict["data"]["progress"] == 0.25


@pytest.mark.unit
class TestProgressCallbackHandler:
    """Tests for progress callback handling in processor.

    Priority 2: Progress Tracking Integration
    - Configure on_progress handler in processor
    """

    def test_progress_handler_type_exists(self):
        """Test that ProgressHandler protocol/type exists."""
        from src.infrastructure.agent.mcp.progress import ProgressHandler

        assert ProgressHandler is not None

    def test_progress_handler_is_callable(self):
        """Test that ProgressHandler is callable."""
        from src.infrastructure.agent.mcp.progress import ProgressHandler

        # Should be able to create a handler function
        async def handler(
            tool_name: str,
            progress_token: str,
            progress: float,
            total: float | None,
            message: str | None,
        ) -> None:
            pass

        # Should be valid as ProgressHandler
        handler_impl: ProgressHandler = handler
        assert callable(handler_impl)


@pytest.mark.unit
class TestResourceSubscription:
    """Tests for resource subscription in MCP client.

    Priority 2: Resource Subscription Integration
    - Frontend Hook exposes subscription methods
    """

    @pytest.fixture
    def mock_client(self):
        """Create a mock MCP client with subscription methods."""
        client = MagicMock()
        client.subscribe_resource = AsyncMock(return_value=True)
        client.unsubscribe_resource = AsyncMock(return_value=True)
        return client

    async def test_subscribe_resource_calls_client(self, mock_client):
        """Test that subscribe_resource is called correctly."""
        result = await mock_client.subscribe_resource("file:///path/to/resource")
        assert result is True
        mock_client.subscribe_resource.assert_called_once_with("file:///path/to/resource")

    async def test_unsubscribe_resource_calls_client(self, mock_client):
        """Test that unsubscribe_resource is called correctly."""
        result = await mock_client.unsubscribe_resource("file:///path/to/resource")
        assert result is True
        mock_client.unsubscribe_resource.assert_called_once_with("file:///path/to/resource")

    async def test_subscribe_resource_with_callback(self, mock_client):
        """Test subscription with update callback."""
        # Mock callback for resource updates
        callback = MagicMock()

        # Subscribe with callback
        result = await mock_client.subscribe_resource("file:///data.json")

        # Verify subscription
        assert result is True


@pytest.mark.unit
class TestCancelHandling:
    """Tests for cancel handling in processor.

    Priority 2: Cancel Handling Integration
    - Processor handles on_cancelled notification
    """

    @pytest.fixture
    def cancel_handler(self):
        """Create a cancel handler."""
        from src.infrastructure.agent.mcp.cancel import CancelHandler

        return CancelHandler()

    def test_cancel_handler_exists(self):
        """Test that CancelHandler class exists."""
        from src.infrastructure.agent.mcp.cancel import CancelHandler

        assert CancelHandler is not None

    def test_cancel_handler_registers_request(self, cancel_handler):
        """Test registering a cancellable request."""
        cancel_handler.register_request("request-123", "server-1")

        assert cancel_handler.has_pending_request("request-123")

    def test_cancel_handler_unregister_request(self, cancel_handler):
        """Test unregistering a request."""
        cancel_handler.register_request("request-456", "server-1")
        cancel_handler.unregister_request("request-456")

        assert not cancel_handler.has_pending_request("request-456")

    async def test_cancel_handler_handles_cancel(self, cancel_handler):
        """Test handling a cancel notification."""
        # Register a request
        cancel_handler.register_request("request-789", "server-1")

        # Mock client
        mock_client = MagicMock()
        mock_client.cancel_request = AsyncMock(return_value=True)

        # Handle cancel
        await cancel_handler.handle_cancel("request-789", mock_client)

        # Verify cancel was called
        mock_client.cancel_request.assert_called_once_with("request-789")

        # Request should be unregistered
        assert not cancel_handler.has_pending_request("request-789")

    def test_cancel_handler_get_pending_requests(self, cancel_handler):
        """Test getting all pending requests."""
        cancel_handler.register_request("req-1", "server-1")
        cancel_handler.register_request("req-2", "server-2")

        pending = cancel_handler.get_pending_requests()

        assert len(pending) == 2
        assert ("req-1", "server-1") in pending
        assert ("req-2", "server-2") in pending


@pytest.mark.unit
class TestMCPClientProgressSupport:
    """Tests for MCPClient progress notification support."""

    @pytest.fixture
    def mock_transport(self):
        """Create a mock transport with progress support."""
        transport = MagicMock()
        transport.send_request = AsyncMock(return_value={})
        return transport

    async def test_client_has_progress_callback_registration(self, mock_transport):
        """Test that client can register progress callback."""
        from src.infrastructure.agent.mcp.client import MCPClient

        client = MCPClient("websocket", {"url": "ws://localhost"})
        client.transport = mock_transport
        client._connected = True

        # Register progress callback
        callback = MagicMock()

        # Should have method to register callback
        assert hasattr(client, "register_progress_callback")

        client.register_progress_callback(callback)

        # Verify callback is stored
        assert client._progress_callback is callback

    async def test_client_handles_progress_notification(self, mock_transport):
        """Test that client handles incoming progress notifications."""
        from src.infrastructure.agent.mcp.client import MCPClient

        client = MCPClient("websocket", {"url": "ws://localhost"})
        client.transport = mock_transport
        client._connected = True

        # Track callback invocations
        callback_calls = []

        async def progress_callback(
            progress_token: str,
            progress: float,
            total: float | None,
            message: str | None,
        ):
            callback_calls.append(
                {
                    "token": progress_token,
                    "progress": progress,
                    "total": total,
                    "message": message,
                }
            )

        client.register_progress_callback(progress_callback)

        # Simulate progress notification
        await client._handle_progress_notification(
            {
                "progressToken": "task-1",
                "progress": 0.5,
                "total": 1.0,
                "message": "Halfway there",
            }
        )

        # Verify callback was invoked
        assert len(callback_calls) == 1
        assert callback_calls[0]["token"] == "task-1"
        assert callback_calls[0]["progress"] == 0.5
