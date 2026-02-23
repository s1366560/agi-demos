"""Tests for AgentSessionRegistry."""

import asyncio

import pytest

from src.infrastructure.agent.hitl.session_registry import (
    AgentSessionRegistry,
    get_session_registry,
    reset_session_registry,
)


@pytest.fixture
def registry():
    """Create a fresh registry for each test."""
    reset_session_registry()
    return AgentSessionRegistry()


@pytest.fixture(autouse=True)
def cleanup():
    """Reset global registry after each test."""
    yield
    reset_session_registry()


@pytest.mark.unit
class TestAgentSessionRegistry:
    """Tests for AgentSessionRegistry."""

    async def test_register_waiter(self, registry):
        """Test registering a waiter."""
        waiter = await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        assert waiter.request_id == "clar_123"
        assert waiter.conversation_id == "conv_456"
        assert waiter.hitl_type == "clarification"
        assert waiter.response_event is not None
        assert registry.has_waiter("clar_123")

    async def test_unregister_waiter(self, registry):
        """Test unregistering a waiter."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        assert registry.has_waiter("clar_123")

        result = await registry.unregister_waiter("clar_123")
        assert result is True
        assert not registry.has_waiter("clar_123")

    async def test_unregister_nonexistent_waiter(self, registry):
        """Test unregistering a non-existent waiter."""
        result = await registry.unregister_waiter("nonexistent")
        assert result is False

    async def test_deliver_response_success(self, registry):
        """Test delivering a response to a waiting session."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        delivered = await registry.deliver_response(
            request_id="clar_123",
            response_data={"answer": "test answer"},
        )

        assert delivered is True
        stats = registry.get_stats()
        assert stats["total_delivered"] == 1

    async def test_deliver_response_not_found(self, registry):
        """Test delivering to non-existent waiter."""
        delivered = await registry.deliver_response(
            request_id="nonexistent",
            response_data={"answer": "test"},
        )

        assert delivered is False

    async def test_wait_for_response_success(self, registry):
        """Test waiting for a response with delivery."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        # Deliver response in background
        async def deliver_later():
            await asyncio.sleep(0.1)
            await registry.deliver_response(
                request_id="clar_123",
                response_data={"answer": "async answer"},
            )

        task = asyncio.create_task(deliver_later())

        # Wait for response
        response = await registry.wait_for_response("clar_123", timeout=5.0)

        assert response == {"answer": "async answer"}
        await task

    async def test_wait_for_response_timeout(self, registry):
        """Test waiting for a response with timeout."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        response = await registry.wait_for_response("clar_123", timeout=0.1)

        assert response is None
        stats = registry.get_stats()
        assert stats["total_timeouts"] == 1

    async def test_get_waiters_by_conversation(self, registry):
        """Test getting all waiters for a conversation."""
        await registry.register_waiter(
            request_id="clar_1",
            conversation_id="conv_456",
            hitl_type="clarification",
        )
        await registry.register_waiter(
            request_id="dec_2",
            conversation_id="conv_456",
            hitl_type="decision",
        )

        waiters = registry.get_waiters_by_conversation("conv_456")

        assert len(waiters) == 2
        request_ids = {w.request_id for w in waiters}
        assert request_ids == {"clar_1", "dec_2"}

    async def test_callback_invoked_on_delivery(self, registry):
        """Test that callback is invoked when response is delivered."""
        callback_data = {}

        async def my_callback(data):
            callback_data["received"] = data

        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
            response_callback=my_callback,
        )

        await registry.deliver_response(
            request_id="clar_123",
            response_data={"answer": "callback test"},
        )

        assert callback_data["received"] == {"answer": "callback test"}

    async def test_cleanup_expired(self, registry):
        """Test cleaning up expired waiters."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        # Clean with 0 max age (everything is expired)
        cleaned = await registry.cleanup_expired(max_age_seconds=0)

        assert cleaned == 1
        assert not registry.has_waiter("clar_123")

    async def test_get_stats(self, registry):
        """Test getting registry statistics."""
        await registry.register_waiter(
            request_id="clar_123",
            conversation_id="conv_456",
            hitl_type="clarification",
        )

        stats = registry.get_stats()

        assert stats["active_waiters"] == 1
        assert stats["active_conversations"] == 1
        assert stats["total_registered"] == 1

    async def test_multiple_conversations(self, registry):
        """Test handling multiple conversations."""
        await registry.register_waiter(
            request_id="clar_1",
            conversation_id="conv_A",
            hitl_type="clarification",
        )
        await registry.register_waiter(
            request_id="clar_2",
            conversation_id="conv_B",
            hitl_type="clarification",
        )

        assert registry.has_waiter("clar_1")
        assert registry.has_waiter("clar_2")

        # Unregister one
        await registry.unregister_waiter("clar_1")

        assert not registry.has_waiter("clar_1")
        assert registry.has_waiter("clar_2")


@pytest.mark.unit
class TestGlobalRegistry:
    """Tests for global registry singleton."""

    def test_get_session_registry_singleton(self):
        """Test that get_session_registry returns singleton."""
        reset_session_registry()

        r1 = get_session_registry()
        r2 = get_session_registry()

        assert r1 is r2

    def test_reset_session_registry(self):
        """Test resetting the global registry."""
        reset_session_registry()
        r1 = get_session_registry()

        reset_session_registry()
        r2 = get_session_registry()

        assert r1 is not r2
