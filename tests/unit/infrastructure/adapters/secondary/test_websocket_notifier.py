"""
Unit tests for WebSocketNotifier.

Tests the lifecycle state change notification system for ProjectReActAgent.
"""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.infrastructure.adapters.secondary.websocket_notifier import (
    WebSocketNotifier,
    LifecycleState,
    LifecycleStateChangeMessage,
)


@pytest.fixture
def mock_connection_manager():
    """Create a mock ConnectionManager."""
    manager = AsyncMock()
    manager.broadcast_to_project = AsyncMock(return_value=1)
    return manager


@pytest.fixture
def notifier(mock_connection_manager):
    """Create a WebSocketNotifier with mock ConnectionManager."""
    return WebSocketNotifier(mock_connection_manager)


class TestLifecycleStateChangeMessage:
    """Tests for LifecycleStateChangeMessage dataclass."""

    def test_create_initializing_message(self):
        """Test creating an initializing state message."""
        message = LifecycleStateChangeMessage(
            project_id="proj-123",
            tenant_id="tenant-456",
            lifecycle_state=LifecycleState.INITIALIZING,
            is_initialized=False,
            is_active=False,
            tool_count=0,
            skill_count=0,
        )

        assert message.project_id == "proj-123"
        assert message.tenant_id == "tenant-456"
        assert message.lifecycle_state == LifecycleState.INITIALIZING
        assert message.is_initialized is False
        assert message.is_active is False
        assert message.tool_count == 0
        assert message.skill_count == 0
        assert message.timestamp is not None

    def test_create_ready_message(self):
        """Test creating a ready state message."""
        message = LifecycleStateChangeMessage(
            project_id="proj-123",
            tenant_id="tenant-456",
            lifecycle_state=LifecycleState.READY,
            is_initialized=True,
            is_active=True,
            tool_count=10,
            skill_count=5,
        )

        assert message.lifecycle_state == LifecycleState.READY
        assert message.is_initialized is True
        assert message.is_active is True
        assert message.tool_count == 10
        assert message.skill_count == 5

    def test_create_error_message(self):
        """Test creating an error state message."""
        error_message = "Initialization failed: connection timeout"
        message = LifecycleStateChangeMessage(
            project_id="proj-123",
            tenant_id="tenant-456",
            lifecycle_state=LifecycleState.ERROR,
            is_initialized=False,
            is_active=False,
            error_message=error_message,
        )

        assert message.lifecycle_state == LifecycleState.ERROR
        assert message.error_message == error_message


class TestWebSocketNotifier:
    """Tests for WebSocketNotifier."""

    @pytest.mark.asyncio
    async def test_notify_lifecycle_state_change(self, notifier, mock_connection_manager):
        """Test notifying lifecycle state change."""
        message = LifecycleStateChangeMessage(
            project_id="proj-123",
            tenant_id="tenant-456",
            lifecycle_state=LifecycleState.READY,
            is_initialized=True,
            is_active=True,
            tool_count=10,
            skill_count=5,
        )

        await notifier.notify_lifecycle_state_change(message)

        # Verify broadcast was called with correct parameters
        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs

        assert call_kwargs["tenant_id"] == "tenant-456"
        assert call_kwargs["project_id"] == "proj-123"

        # Verify message structure
        sent_message = call_kwargs["message"]
        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["project_id"] == "proj-123"
        assert sent_message["data"]["lifecycle_state"] == "ready"
        assert sent_message["data"]["is_initialized"] is True
        assert sent_message["data"]["tool_count"] == 10

    @pytest.mark.asyncio
    async def test_notify_initializing(self, notifier, mock_connection_manager):
        """Test notify_initializing convenience method."""
        await notifier.notify_initializing(
            tenant_id="tenant-456",
            project_id="proj-123",
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "initializing"
        assert sent_message["data"]["is_initialized"] is False

    @pytest.mark.asyncio
    async def test_notify_ready(self, notifier, mock_connection_manager):
        """Test notify_ready convenience method."""
        await notifier.notify_ready(
            tenant_id="tenant-456",
            project_id="proj-123",
            tool_count=10,
            skill_count=5,
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "ready"
        assert sent_message["data"]["is_initialized"] is True
        assert sent_message["data"]["tool_count"] == 10
        assert sent_message["data"]["skill_count"] == 5

    @pytest.mark.asyncio
    async def test_notify_executing(self, notifier, mock_connection_manager):
        """Test notify_executing convenience method."""
        await notifier.notify_executing(
            tenant_id="tenant-456",
            project_id="proj-123",
            conversation_id="conv-789",
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "executing"
        assert sent_message["data"]["conversation_id"] == "conv-789"

    @pytest.mark.asyncio
    async def test_notify_paused(self, notifier, mock_connection_manager):
        """Test notify_paused convenience method."""
        await notifier.notify_paused(
            tenant_id="tenant-456",
            project_id="proj-123",
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "paused"
        assert sent_message["data"]["is_active"] is False

    @pytest.mark.asyncio
    async def test_notify_shutting_down(self, notifier, mock_connection_manager):
        """Test notify_shutting_down convenience method."""
        await notifier.notify_shutting_down(
            tenant_id="tenant-456",
            project_id="proj-123",
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "shutting_down"

    @pytest.mark.asyncio
    async def test_notify_error(self, notifier, mock_connection_manager):
        """Test notify_error convenience method."""
        error_msg = "Connection timeout"
        await notifier.notify_error(
            tenant_id="tenant-456",
            project_id="proj-123",
            error_message=error_msg,
        )

        mock_connection_manager.broadcast_to_project.assert_called_once()
        call_kwargs = mock_connection_manager.broadcast_to_project.call_args.kwargs
        sent_message = call_kwargs["message"]

        assert sent_message["type"] == "lifecycle_state_change"
        assert sent_message["data"]["lifecycle_state"] == "error"
        assert sent_message["data"]["error_message"] == error_msg

    @pytest.mark.asyncio
    async def test_notify_with_zero_subscribers(self, notifier, mock_connection_manager):
        """Test notification when no subscribers (broadcast returns 0)."""
        mock_connection_manager.broadcast_to_project.return_value = 0

        await notifier.notify_ready(
            tenant_id="tenant-456",
            project_id="proj-123",
            tool_count=10,
        )

        # Should still attempt broadcast
        mock_connection_manager.broadcast_to_project.assert_called_once()


class TestConnectionManagerIntegration:
    """Integration tests with ConnectionManager."""

    @pytest.mark.asyncio
    async def test_broadcast_to_project_in_manager(self):
        """Test that ConnectionManager has broadcast_to_project method."""
        from src.infrastructure.adapters.primary.web.routers.agent_websocket import (
            ConnectionManager,
        )

        manager = ConnectionManager()

        # Verify method exists
        assert hasattr(manager, "broadcast_to_project")
        assert callable(manager.broadcast_to_project)

    @pytest.mark.asyncio
    async def test_connection_manager_manages_project_subscriptions(self):
        """Test that ConnectionManager can track project subscriptions."""
        from src.infrastructure.adapters.primary.web.routers.agent_websocket import (
            ConnectionManager,
        )

        manager = ConnectionManager()
        user_id = "user-123"
        session_id = "session-456"
        project_id = "proj-789"

        # Use a mock websocket
        ws = AsyncMock()
        ws.send_json = AsyncMock()

        await manager.connect(user_id, session_id, ws)

        # Verify project_subscriptions dict exists and can store subscriptions
        assert hasattr(manager, "project_subscriptions")

        # Clean up
        await manager.disconnect(session_id)
