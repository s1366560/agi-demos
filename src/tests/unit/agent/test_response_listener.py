"""Tests for HITLResponseListener."""

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.hitl.response_listener import HITLResponseListener
from src.infrastructure.agent.hitl.session_registry import (
    AgentSessionRegistry,
    reset_session_registry,
)


@pytest.fixture
def mock_redis():
    """Create a mock Redis client."""
    redis = AsyncMock()
    redis.xgroup_create = AsyncMock()
    redis.xreadgroup = AsyncMock(return_value=[])
    redis.xack = AsyncMock()
    return redis


@pytest.fixture
def registry():
    """Create a fresh registry for each test."""
    reset_session_registry()
    return AgentSessionRegistry()


@pytest.fixture
def listener(mock_redis, registry):
    """Create a listener with mocked dependencies."""
    return HITLResponseListener(
        redis_client=mock_redis,
        session_registry=registry,
        worker_id="test-worker-1",
    )


@pytest.fixture(autouse=True)
def cleanup():
    """Reset global registry after each test."""
    yield
    reset_session_registry()


@pytest.mark.unit
class TestHITLResponseListener:
    """Tests for HITLResponseListener."""

    async def test_get_stream_key(self, listener):
        """Test stream key generation."""
        key = listener._get_stream_key("tenant1", "project1")
        assert key == "hitl:response:tenant1:project1"

    async def test_add_project(self, listener, mock_redis):
        """Test adding a project to listen."""
        await listener.add_project("tenant1", "project1")

        assert ("tenant1", "project1") in listener._projects
        mock_redis.xgroup_create.assert_called_once()

    async def test_add_project_group_exists(self, listener, mock_redis):
        """Test adding a project when group already exists."""
        import redis.asyncio as aioredis

        mock_redis.xgroup_create.side_effect = aioredis.ResponseError("BUSYGROUP")

        await listener.add_project("tenant1", "project1")

        assert ("tenant1", "project1") in listener._projects

    async def test_remove_project(self, listener):
        """Test removing a project."""
        listener._projects.add(("tenant1", "project1"))

        await listener.remove_project("tenant1", "project1")

        assert ("tenant1", "project1") not in listener._projects

    async def test_start_stop(self, listener):
        """Test starting and stopping the listener."""
        await listener.start()
        assert listener._running is True
        assert listener._listen_task is not None

        await listener.stop()
        assert listener._running is False

    async def test_handle_message_delivery(self, listener, registry, mock_redis):
        """Test message handling with successful delivery."""
        # Register a waiter
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        # Prepare message
        message_data = {
            "request_id": "clar_123",
            "response_data": {"answer": "test"},
        }
        fields = {b"data": json.dumps(message_data).encode()}

        # Handle message
        await listener._handle_message(
            "hitl:response:tenant1:project1",
            "12345-0",
            fields,
        )

        # Verify delivery
        assert listener._messages_received == 1
        assert listener._messages_delivered == 1
        mock_redis.xack.assert_called_once()

    async def test_handle_message_no_waiter(self, listener, mock_redis):
        """Test message handling when no waiter exists."""
        message_data = {
            "request_id": "nonexistent",
            "response_data": {"answer": "test"},
        }
        fields = {b"data": json.dumps(message_data).encode()}

        await listener._handle_message(
            "hitl:response:tenant1:project1",
            "12345-0",
            fields,
        )

        assert listener._messages_received == 1
        assert listener._messages_skipped == 1
        mock_redis.xack.assert_called_once()

    async def test_handle_message_invalid_json(self, listener, mock_redis):
        """Test handling invalid JSON message."""
        fields = {b"data": b"invalid json"}

        await listener._handle_message(
            "hitl:response:tenant1:project1",
            "12345-0",
            fields,
        )

        assert listener._errors == 1
        mock_redis.xack.assert_called_once()

    async def test_handle_message_missing_request_id(self, listener, mock_redis):
        """Test handling message without request_id."""
        message_data = {"response_data": {"answer": "test"}}
        fields = {b"data": json.dumps(message_data).encode()}

        await listener._handle_message(
            "hitl:response:tenant1:project1",
            "12345-0",
            fields,
        )

        mock_redis.xack.assert_called_once()

    async def test_get_stats(self, listener):
        """Test getting listener statistics."""
        listener._messages_received = 100
        listener._messages_delivered = 80
        listener._messages_skipped = 15
        listener._errors = 5

        stats = listener.get_stats()

        assert stats["running"] is False
        assert stats["worker_id"] == "test-worker-1"
        assert stats["messages_received"] == 100
        assert stats["messages_delivered"] == 80
        assert stats["delivery_rate"] == 0.8


@pytest.mark.unit
class TestListenLoop:
    """Tests for the main listen loop."""

    async def test_listen_loop_no_projects(self, listener):
        """Test listen loop with no projects."""
        # Start listener
        await listener.start()

        # Let it run briefly
        await asyncio.sleep(0.1)

        # Stop
        await listener.stop()

        # Should have looped but done nothing
        assert listener._running is False

    async def test_listen_loop_processes_messages(self, listener, mock_redis, registry):
        """Test listen loop processes messages correctly."""
        # Register waiter before adding project
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        # Mock xreadgroup to return a message once, then empty (fast response)
        message_data = {
            "request_id": "clar_123",
            "response_data": {"answer": "loop test"},
        }
        call_count = 0
        message_delivered = asyncio.Event()

        original_handle_message = listener._handle_message

        async def tracked_handle_message(*args, **kwargs):
            await original_handle_message(*args, **kwargs)
            message_delivered.set()

        listener._handle_message = tracked_handle_message

        async def mock_xreadgroup_func(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [
                    (
                        b"hitl:response:tenant1:project1",
                        [(b"12345-0", {b"data": json.dumps(message_data).encode()})],
                    )
                ]
            # Return empty but don't block - short sleep to simulate fast poll
            await asyncio.sleep(0.01)
            return []

        mock_redis.xreadgroup = mock_xreadgroup_func

        # Add project after mock is set up
        await listener.add_project("tenant1", "project1")

        # Start listener
        await listener.start()

        # Wait for message processing with timeout
        try:
            await asyncio.wait_for(message_delivered.wait(), timeout=2.0)
        except TimeoutError:
            pass  # Test will fail on assertion anyway

        # Stop
        await listener.stop()

        # Verify message was delivered
        assert listener._messages_delivered == 1
