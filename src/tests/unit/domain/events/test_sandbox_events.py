"""Unit tests for Sandbox domain events.

Tests Sandbox-related events:
- sandbox_created
- sandbox_terminated
- sandbox_status
- desktop_started
- desktop_stopped
- desktop_status
- terminal_started
- terminal_stopped
- terminal_status
"""

import pytest

from src.domain.events.agent_events import (
    AgentEventType,
    AgentSandboxCreatedEvent,
    AgentSandboxTerminatedEvent,
    AgentSandboxStatusEvent,
    AgentDesktopStartedEvent,
    AgentDesktopStoppedEvent,
    AgentDesktopStatusEvent,
    AgentTerminalStartedEvent,
    AgentTerminalStoppedEvent,
    AgentTerminalStatusEvent,
)


class TestSandboxEvents:
    """Test Sandbox domain events."""

    def test_sandbox_created_event(self):
        """Test sandbox_created event creation."""
        event = AgentSandboxCreatedEvent(
            sandbox_id="sb_123",
            project_id="proj_456",
            status="running",
            endpoint="ws://localhost:8765",
            websocket_url="ws://localhost:8765",
        )

        assert event.event_type == AgentEventType.SANDBOX_CREATED
        assert event.sandbox_id == "sb_123"
        assert event.project_id == "proj_456"
        assert event.status == "running"
        assert event.endpoint == "ws://localhost:8765"
        assert event.websocket_url == "ws://localhost:8765"

    def test_sandbox_created_event_to_dict(self):
        """Test sandbox_created event to_event_dict conversion."""
        event = AgentSandboxCreatedEvent(
            sandbox_id="sb_123",
            project_id="proj_456",
            status="running",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "sandbox_created"
        assert event_dict["data"]["sandbox_id"] == "sb_123"
        assert event_dict["data"]["project_id"] == "proj_456"
        assert event_dict["data"]["status"] == "running"
        assert "timestamp" in event_dict

    def test_sandbox_terminated_event(self):
        """Test sandbox_terminated event creation."""
        event = AgentSandboxTerminatedEvent(
            sandbox_id="sb_123",
        )

        assert event.event_type == AgentEventType.SANDBOX_TERMINATED
        assert event.sandbox_id == "sb_123"

    def test_sandbox_status_event(self):
        """Test sandbox_status event creation."""
        event = AgentSandboxStatusEvent(
            sandbox_id="sb_123",
            status="stopped",
        )

        assert event.event_type == AgentEventType.SANDBOX_STATUS
        assert event.sandbox_id == "sb_123"
        assert event.status == "stopped"

    def test_desktop_started_event(self):
        """Test desktop_started event creation."""
        event = AgentDesktopStartedEvent(
            sandbox_id="sb_123",
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1280x720",
            port=6080,
        )

        assert event.event_type == AgentEventType.DESKTOP_STARTED
        assert event.sandbox_id == "sb_123"
        assert event.url == "http://localhost:6080/vnc.html"
        assert event.display == ":1"
        assert event.resolution == "1280x720"
        assert event.port == 6080

    def test_desktop_started_event_to_dict(self):
        """Test desktop_started event to_event_dict conversion."""
        event = AgentDesktopStartedEvent(
            sandbox_id="sb_123",
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1920x1080",
            port=6080,
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "desktop_started"
        assert event_dict["data"]["sandbox_id"] == "sb_123"
        assert event_dict["data"]["url"] == "http://localhost:6080/vnc.html"
        assert event_dict["data"]["display"] == ":1"
        assert event_dict["data"]["resolution"] == "1920x1080"
        assert event_dict["data"]["port"] == 6080
        assert "timestamp" in event_dict

    def test_desktop_stopped_event(self):
        """Test desktop_stopped event creation."""
        event = AgentDesktopStoppedEvent(
            sandbox_id="sb_123",
        )

        assert event.event_type == AgentEventType.DESKTOP_STOPPED
        assert event.sandbox_id == "sb_123"

    def test_desktop_status_event(self):
        """Test desktop_status event creation."""
        event = AgentDesktopStatusEvent(
            sandbox_id="sb_123",
            running=True,
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1280x720",
            port=6080,
        )

        assert event.event_type == AgentEventType.DESKTOP_STATUS
        assert event.sandbox_id == "sb_123"
        assert event.running is True
        assert event.url == "http://localhost:6080/vnc.html"

    def test_desktop_status_event_not_running(self):
        """Test desktop_status event when not running."""
        event = AgentDesktopStatusEvent(
            sandbox_id="sb_123",
            running=False,
        )

        assert event.event_type == AgentEventType.DESKTOP_STATUS
        assert event.sandbox_id == "sb_123"
        assert event.running is False
        assert event.url is None

    def test_terminal_started_event(self):
        """Test terminal_started event creation."""
        event = AgentTerminalStartedEvent(
            sandbox_id="sb_123",
            url="ws://localhost:7681",
            port=7681,
            session_id="sess_abc",
            pid=12345,
        )

        assert event.event_type == AgentEventType.TERMINAL_STARTED
        assert event.sandbox_id == "sb_123"
        assert event.url == "ws://localhost:7681"
        assert event.port == 7681
        assert event.session_id == "sess_abc"
        assert event.pid == 12345

    def test_terminal_started_event_to_dict(self):
        """Test terminal_started event to_event_dict conversion."""
        event = AgentTerminalStartedEvent(
            sandbox_id="sb_123",
            url="ws://localhost:7681",
            port=7681,
            session_id="sess_abc",
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "terminal_started"
        assert event_dict["data"]["sandbox_id"] == "sb_123"
        assert event_dict["data"]["url"] == "ws://localhost:7681"
        assert event_dict["data"]["port"] == 7681
        assert event_dict["data"]["session_id"] == "sess_abc"

    def test_terminal_stopped_event(self):
        """Test terminal_stopped event creation."""
        event = AgentTerminalStoppedEvent(
            sandbox_id="sb_123",
            session_id="sess_abc",
        )

        assert event.event_type == AgentEventType.TERMINAL_STOPPED
        assert event.sandbox_id == "sb_123"
        assert event.session_id == "sess_abc"

    def test_terminal_status_event(self):
        """Test terminal_status event creation."""
        event = AgentTerminalStatusEvent(
            sandbox_id="sb_123",
            running=True,
            url="ws://localhost:7681",
            port=7681,
            session_id="sess_abc",
            pid=12345,
        )

        assert event.event_type == AgentEventType.TERMINAL_STATUS
        assert event.sandbox_id == "sb_123"
        assert event.running is True
        assert event.url == "ws://localhost:7681"

    def test_terminal_status_event_not_running(self):
        """Test terminal_status event when not running."""
        event = AgentTerminalStatusEvent(
            sandbox_id="sb_123",
            running=False,
        )

        assert event.event_type == AgentEventType.TERMINAL_STATUS
        assert event.sandbox_id == "sb_123"
        assert event.running is False
        assert event.url is None

    def test_all_sandbox_event_types_exist(self):
        """Test that all sandbox event types are defined in AgentEventType."""
        expected_types = [
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

        for expected in expected_types:
            assert expected in [e.value for e in AgentEventType], f"Missing event type: {expected}"

    def test_all_sandbox_event_types_in_frontend_list(self):
        """Test that sandbox event types are included in frontend list."""
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
            assert event_type in frontend_types, f"Sandbox event type {event_type} not in frontend list"
