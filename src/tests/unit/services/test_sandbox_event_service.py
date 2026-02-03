"""Unit tests for SandboxEventPublisher service.

Tests the Sandbox SSE event emission logic.
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.application.services.sandbox_event_service import SandboxEventPublisher


class TestSandboxEventPublisher:
    """Test SandboxEventPublisher."""

    @pytest.fixture
    def mock_event_bus(self):
        """Create a mock event bus."""
        event_bus = Mock()
        event_bus.stream_add = AsyncMock(return_value="msg-id-123")
        event_bus.publish = AsyncMock()
        return event_bus

    @pytest.fixture
    def publisher(self, mock_event_bus):
        """Create publisher with mock event bus."""
        return SandboxEventPublisher(event_bus=mock_event_bus)

    @pytest.mark.asyncio
    async def test_publish_sandbox_created(self, publisher, mock_event_bus):
        """Test publishing sandbox_created event."""
        result = await publisher.publish_sandbox_created(
            project_id="proj-123",
            sandbox_id="sb-456",
            status="running",
            endpoint="ws://localhost:8765",
            websocket_url="ws://localhost:8765",
        )

        # Should return message ID from stream_add
        assert result == "msg-id-123"

        # Should call stream_add with correct stream key
        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        stream_key = call_args[0][0]
        event_dict = call_args[0][1]

        assert stream_key == "sandbox:events:proj-123"
        assert event_dict["type"] == "sandbox_created"
        assert event_dict["data"]["sandbox_id"] == "sb-456"
        assert event_dict["data"]["project_id"] == "proj-123"
        assert event_dict["data"]["status"] == "running"
        assert event_dict["project_id"] == "proj-123"  # Routing key

        # Should also publish to pub/sub
        mock_event_bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_sandbox_terminated(self, publisher, mock_event_bus):
        """Test publishing sandbox_terminated event."""
        result = await publisher.publish_sandbox_terminated(
            project_id="proj-123",
            sandbox_id="sb-456",
        )

        assert result == "msg-id-123"

        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        event_dict = call_args[0][1]

        assert event_dict["type"] == "sandbox_terminated"
        assert event_dict["data"]["sandbox_id"] == "sb-456"

    @pytest.mark.asyncio
    async def test_publish_desktop_started(self, publisher, mock_event_bus):
        """Test publishing desktop_started event."""
        result = await publisher.publish_desktop_started(
            project_id="proj-123",
            sandbox_id="sb-456",
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1920x1080",
            port=6080,
        )

        assert result == "msg-id-123"

        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        event_dict = call_args[0][1]

        assert event_dict["type"] == "desktop_started"
        assert event_dict["data"]["sandbox_id"] == "sb-456"
        assert event_dict["data"]["url"] == "http://localhost:6080/vnc.html"
        assert event_dict["data"]["display"] == ":1"
        assert event_dict["data"]["resolution"] == "1920x1080"
        assert event_dict["data"]["port"] == 6080

    @pytest.mark.asyncio
    async def test_publish_desktop_stopped(self, publisher, mock_event_bus):
        """Test publishing desktop_stopped event."""
        result = await publisher.publish_desktop_stopped(
            project_id="proj-123",
            sandbox_id="sb-456",
        )

        assert result == "msg-id-123"

        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        event_dict = call_args[0][1]

        assert event_dict["type"] == "desktop_stopped"
        assert event_dict["data"]["sandbox_id"] == "sb-456"

    @pytest.mark.asyncio
    async def test_publish_terminal_started(self, publisher, mock_event_bus):
        """Test publishing terminal_started event."""
        result = await publisher.publish_terminal_started(
            project_id="proj-123",
            sandbox_id="sb-456",
            url="ws://localhost:7681",
            port=7681,
            session_id="sess-abc",
            pid=12345,
        )

        assert result == "msg-id-123"

        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        event_dict = call_args[0][1]

        assert event_dict["type"] == "terminal_started"
        assert event_dict["data"]["sandbox_id"] == "sb-456"
        assert event_dict["data"]["url"] == "ws://localhost:7681"
        assert event_dict["data"]["port"] == 7681
        assert event_dict["data"]["session_id"] == "sess-abc"
        assert event_dict["data"]["pid"] == 12345

    @pytest.mark.asyncio
    async def test_publish_terminal_stopped(self, publisher, mock_event_bus):
        """Test publishing terminal_stopped event."""
        result = await publisher.publish_terminal_stopped(
            project_id="proj-123",
            sandbox_id="sb-456",
            session_id="sess-abc",
        )

        assert result == "msg-id-123"

        mock_event_bus.stream_add.assert_called_once()
        call_args = mock_event_bus.stream_add.call_args
        event_dict = call_args[0][1]

        assert event_dict["type"] == "terminal_stopped"
        assert event_dict["data"]["sandbox_id"] == "sb-456"
        assert event_dict["data"]["session_id"] == "sess-abc"

    @pytest.mark.asyncio
    async def test_publish_without_event_bus(self, caplog):
        """Test publishing when event bus is not available."""
        publisher = SandboxEventPublisher(event_bus=None)

        result = await publisher.publish_sandbox_created(
            project_id="proj-123",
            sandbox_id="sb-456",
            status="running",
        )

        # Should return empty string without crashing
        assert result == ""

    @pytest.mark.asyncio
    async def test_publish_stream_maxlen(self, publisher, mock_event_bus):
        """Test that stream_add is called with maxlen=1000."""
        await publisher.publish_sandbox_created(
            project_id="proj-123",
            sandbox_id="sb-456",
            status="running",
        )

        call_args = mock_event_bus.stream_add.call_args
        # Check maxlen parameter
        assert call_args[1].get("maxlen") == 1000

    @pytest.mark.asyncio
    async def test_all_sandbox_event_types_supported(self):
        """Verify all sandbox event types are published correctly."""
        # This test ensures we don't forget to add any event type
        from src.domain.events.agent_events import get_frontend_event_types

        frontend_types = get_frontend_event_types()

        sandbox_types = [
            "sandbox_created",
            "sandbox_terminated",
            "sandbox_status",
            "desktop_started",
            "desktop_stopped",
            "desktop_status",
            "terminal_started",
            "terminal_stopped",
            "terminal_status",
        ]

        for event_type in sandbox_types:
            assert event_type in frontend_types, f"Event type {event_type} not in frontend list"
