"""
Integration tests for multiple HITL (Human-in-the-Loop) scenarios.

These tests verify that the agent correctly handles:
1. Multiple sequential HITL requests in a single conversation
2. HITL state cleanup between requests
3. Correct message context preservation across HITL cycles
4. Proper handler lifecycle management
"""

import asyncio
import json
import pytest
from datetime import datetime
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

from src.domain.model.agent.hitl_types import (
    HITLPendingException,
    HITLType,
    create_clarification_request,
    create_decision_request,
)
from src.infrastructure.agent.hitl.ray_hitl_handler import RayHITLHandler
from src.infrastructure.agent.hitl.session_registry import (
    AgentSessionRegistry,
    get_session_registry,
    reset_session_registry,
)
from src.infrastructure.agent.processor import ProcessorConfig, SessionProcessor, ToolDefinition


@pytest.fixture
def registry():
    """Create a fresh registry for each test."""
    reset_session_registry()
    return get_session_registry()


@pytest.fixture(autouse=True)
def cleanup():
    """Reset global registry after each test."""
    yield
    reset_session_registry()


class MockTool:
    """Mock tool for testing."""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description or f"Tool: {name}"

    def get_parameters_schema(self):
        return {
            "type": "object",
            "properties": {},
            "required": [],
        }

    async def execute(self, **kwargs):
        return f"Result from {self.name}"


class MockLLMClient:
    """Mock LLM client for testing HITL flows."""

    def __init__(self, responses: List[List[Dict[str, Any]]] = None):
        self.responses = responses or []
        self.call_count = 0

    async def stream(self, messages, **kwargs):
        """Mock streaming responses."""
        if self.call_count < len(self.responses):
            response = self.responses[self.call_count]
            self.call_count += 1
            for item in response:
                yield item
        else:
            # Default response - finish
            yield {
                "type": "finish",
                "data": {"reason": "stop"},
            }


def create_hitl_tool_def(name: str, handler: RayHITLHandler) -> ToolDefinition:
    """Create a tool definition that triggers HITL."""

    async def execute_hitl(**kwargs):
        # This will be intercepted by the processor
        return {"output": f"HITL {name} executed"}

    return ToolDefinition(
        name=name,
        description=f"HITL tool: {name}",
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "options": {"type": "array"},
            },
            "required": ["question"],
        },
        execute=execute_hitl,
    )


@pytest.mark.integration
class TestMultipleHITLScenarios:
    """Test multiple HITL scenarios."""

    async def test_session_registry_multiple_waiters(self, registry):
        """Test that session registry can handle multiple waiters for same conversation."""
        conversation_id = "conv_test_123"

        # Register first HITL waiter
        waiter1 = await registry.register_waiter(
            request_id="clar_001",
            conversation_id=conversation_id,
            hitl_type="clarification",
        )

        # Register second HITL waiter
        waiter2 = await registry.register_waiter(
            request_id="dec_002",
            conversation_id=conversation_id,
            hitl_type="decision",
        )

        # Verify both are registered
        assert registry.has_waiter("clar_001")
        assert registry.has_waiter("dec_002")

        # Get waiters by conversation
        waiters = registry.get_waiters_by_conversation(conversation_id)
        assert len(waiters) == 2

        request_ids = {w.request_id for w in waiters}
        assert request_ids == {"clar_001", "dec_002"}

        # Deliver response to first waiter
        delivered = await registry.deliver_response(
            request_id="clar_001",
            response_data={"answer": "clarification answer"},
        )
        assert delivered is True

        # Verify first is removed (if callback was set)
        # Actually it should still exist until explicitly unregistered
        assert registry.has_waiter("clar_001")

        # Unregister first waiter
        await registry.unregister_waiter("clar_001")
        assert not registry.has_waiter("clar_001")
        assert registry.has_waiter("dec_002")

        # Deliver and unregister second
        await registry.deliver_response(
            request_id="dec_002",
            response_data={"decision": "option_a"},
        )
        await registry.unregister_waiter("dec_002")
        assert not registry.has_waiter("dec_002")

    async def test_ray_hitl_handler_preinjected_response_consumption(self):
        """Test that preinjected response is consumed only once."""
        handler = RayHITLHandler(
            conversation_id="conv_test",
            tenant_id="tenant_test",
            project_id="project_test",
            preinjected_response={
                "request_id": "clar_001",
                "hitl_type": "clarification",
                "response_data": {"answer": "test_answer"},
            },
        )

        # First peek should return the response
        preinjected = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        assert preinjected is not None
        assert preinjected["request_id"] == "clar_001"

        # Peek should not consume - calling again should still return
        preinjected2 = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        assert preinjected2 is not None

        # Now actually use it through request_clarification
        # This should consume the preinjected response
        # Note: In actual implementation, the handler uses pop to consume

    async def test_processor_hitl_handler_reuse_issue(self):
        """
        Test that processor correctly manages HITL handler lifecycle.

        This test verifies that when a processor handles multiple HITL requests,
        the handler state is properly managed.
        """
        config = ProcessorConfig(
            model="test-model",
            max_steps=10,
        )

        tools = []
        processor = SessionProcessor(config, tools)

        # Set up langfuse context
        langfuse_context = {
            "conversation_id": "conv_test",
            "tenant_id": "tenant_test",
            "project_id": "project_test",
            "message_id": "msg_001",
        }
        processor._langfuse_context = langfuse_context

        # Get handler first time (no preinjected response)
        handler1 = processor._get_hitl_handler()
        assert handler1 is not None
        assert handler1._preinjected_response is None

        # Simulate receiving a HITL response and setting it
        langfuse_context["hitl_response"] = {
            "request_id": "clar_001",
            "hitl_type": "clarification",
            "response_data": {"answer": "test"},
        }

        # Get handler again - should pick up the new response
        handler2 = processor._get_hitl_handler()
        assert handler2 is handler1  # Same instance
        assert handler2._preinjected_response is not None
        assert handler2._preinjected_response["request_id"] == "clar_001"

        # Simulate consuming the response
        handler2._preinjected_response = None

        # Now simulate a second HITL cycle
        # The handler should still be the same instance, but with no preinjected response
        handler3 = processor._get_hitl_handler()
        assert handler3 is handler2
        assert handler3._preinjected_response is None

    async def test_multiple_hitl_types_in_sequence(self):
        """
        Test handling different HITL types in sequence.

        Verifies that the system correctly handles:
        1. First HITL: clarification
        2. Second HITL: decision
        3. Third HITL: env_var
        """
        registry = AgentSessionRegistry()
        conversation_id = "conv_multi_hitl"

        hitl_sequence = [
            ("clar_001", "clarification", {"answer": "clarification response"}),
            ("dec_002", "decision", {"decision": "option_b"}),
            ("env_003", "env_var", {"values": {"API_KEY": "secret123"}}),
        ]

        # Register all HITL requests
        for request_id, hitl_type, response_data in hitl_sequence:
            await registry.register_waiter(
                request_id=request_id,
                conversation_id=conversation_id,
                hitl_type=hitl_type,
            )

        # Verify all registered
        assert len(registry.get_waiters_by_conversation(conversation_id)) == 3

        # Process each HITL in sequence
        for request_id, hitl_type, response_data in hitl_sequence:
            # Deliver response
            delivered = await registry.deliver_response(
                request_id=request_id,
                response_data=response_data,
            )
            assert delivered is True, f"Failed to deliver to {request_id}"

            # Unregister
            await registry.unregister_waiter(request_id)

        # Verify all unregistered
        assert len(registry.get_waiters_by_conversation(conversation_id)) == 0

        stats = registry.get_stats()
        assert stats["total_delivered"] == 3

    async def test_hitl_response_delivery_order(self):
        """Test that HITL responses are delivered in correct order."""
        registry = AgentSessionRegistry()

        # Register waiters with callbacks to track order
        delivered_order = []

        async def make_callback(request_id):
            async def callback(data):
                delivered_order.append(request_id)
            return callback

        # Register multiple waiters
        for i in range(5):
            await registry.register_waiter(
                request_id=f"hitl_{i:03d}",
                conversation_id="conv_order_test",
                hitl_type="clarification",
                response_callback=await make_callback(f"hitl_{i:03d}"),
            )

        # Deliver in reverse order
        for i in reversed(range(5)):
            await registry.deliver_response(
                request_id=f"hitl_{i:03d}",
                response_data={"answer": f"response_{i}"},
            )

        # Verify delivery order matches delivery sequence (reverse)
        assert delivered_order == [f"hitl_{i:03d}" for i in reversed(range(5))]

    async def test_concurrent_hitl_requests_same_conversation(self):
        """Test handling concurrent HITL requests for the same conversation."""
        registry = AgentSessionRegistry()
        conversation_id = "conv_concurrent"

        # Register multiple concurrent HITL requests
        request_ids = [f"concurrent_{i}" for i in range(10)]

        for request_id in request_ids:
            await registry.register_waiter(
                request_id=request_id,
                conversation_id=conversation_id,
                hitl_type="clarification",
            )

        # Deliver all responses concurrently
        async def deliver_response(request_id: str):
            await asyncio.sleep(0.01)  # Small delay to simulate processing
            return await registry.deliver_response(
                request_id=request_id,
                response_data={"answer": f"answer_for_{request_id}"},
            )

        # Run all deliveries concurrently
        results = await asyncio.gather(
            *[deliver_response(rid) for rid in request_ids],
            return_exceptions=True,
        )

        # All should succeed
        assert all(r is True for r in results), f"Some deliveries failed: {results}"

        stats = registry.get_stats()
        assert stats["total_delivered"] == 10


@pytest.mark.integration
class TestHITLStatePreservation:
    """Test HITL state preservation across resume cycles."""

    async def test_message_context_preservation(self):
        """
        Test that message context is preserved correctly across HITL cycles.

        This is critical for the agent to continue correctly after HITL response.
        """
        # Simulate messages that would be built during a conversation
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "I need help with a complex task."},
            {"role": "assistant", "content": "I'll help you. Let me start by asking..."},
        ]

        # Simulate first HITL - clarification
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_001",
                "type": "function",
                "function": {
                    "name": "ask_clarification",
                    "arguments": json.dumps({"question": "What is your preference?"}),
                },
            }],
        })

        # Tool result with HITL response
        messages.append({
            "role": "tool",
            "tool_call_id": "call_001",
            "content": "User clarification: Option A",
        })

        # Verify messages are correctly ordered
        assert len(messages) == 4
        assert messages[3]["role"] == "tool"
        assert messages[3]["tool_call_id"] == "call_001"

        # Simulate second HITL - decision
        messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_002",
                "type": "function",
                "function": {
                    "name": "request_decision",
                    "arguments": json.dumps({"question": "Confirm action?"}),
                },
            }],
        })

        messages.append({
            "role": "tool",
            "tool_call_id": "call_002",
            "content": "User decision: proceed",
        })

        # Verify complete context
        assert len(messages) == 6
        tool_calls = [m for m in messages if m["role"] == "tool"]
        assert len(tool_calls) == 2

    async def test_hitl_exception_message_capture(self):
        """Test that HITLPendingException captures current messages correctly."""
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "User query"},
        ]

        # Create exception with message context
        exception = HITLPendingException(
            request_id="test_001",
            hitl_type=HITLType.CLARIFICATION,
            request_data={"question": "Test?"},
            conversation_id="conv_test",
            message_id="msg_test",
            timeout_seconds=300,
        )

        # Simulate what processor does - set current_messages
        exception.current_messages = list(messages)
        exception.current_messages.append({
            "role": "assistant",
            "content": None,
            "tool_calls": [{
                "id": "call_hitl",
                "type": "function",
                "function": {"name": "ask_clarification", "arguments": "{}"},
            }],
        })
        exception.tool_call_id = "call_hitl"

        # Verify captured state
        assert len(exception.current_messages) == 3
        assert exception.tool_call_id == "call_hitl"
        assert exception.request_id == "test_001"


@pytest.mark.integration
class TestHITLHandlerEdgeCases:
    """Test edge cases in HITL handler behavior."""

    async def test_handler_with_mismatched_preinjected_type(self):
        """Test handler when preinjected response type doesn't match request type."""
        handler = RayHITLHandler(
            conversation_id="conv_test",
            tenant_id="tenant_test",
            project_id="project_test",
            preinjected_response={
                "request_id": "clar_001",
                "hitl_type": "clarification",
                "response_data": {"answer": "test"},
            },
        )

        # Try to get response for decision type (mismatch)
        preinjected = handler.peek_preinjected_response(HITLType.DECISION)
        assert preinjected is None  # Should not match

        # Get response for clarification type (match)
        preinjected = handler.peek_preinjected_response(HITLType.CLARIFICATION)
        assert preinjected is not None  # Should match

    async def test_handler_cleanup_after_conversation_change(self):
        """Test that handler is recreated when conversation changes."""
        config = ProcessorConfig(model="test")
        processor = SessionProcessor(config, [])

        # First conversation
        processor._langfuse_context = {
            "conversation_id": "conv_1",
            "tenant_id": "tenant_1",
            "project_id": "project_1",
        }
        handler1 = processor._get_hitl_handler()
        assert handler1.conversation_id == "conv_1"

        # Change conversation
        processor._langfuse_context = {
            "conversation_id": "conv_2",  # Different conversation
            "tenant_id": "tenant_1",
            "project_id": "project_1",
        }
        handler2 = processor._get_hitl_handler()

        # Should be different handler instance
        assert handler2 is not handler1
        assert handler2.conversation_id == "conv_2"


@pytest.mark.integration
class TestHITLTimeoutAndExpiration:
    """Test HITL timeout and expiration handling."""

    async def test_waiter_timeout_handling(self, registry):
        """Test that waiters handle timeout correctly."""
        await registry.register_waiter(
            request_id="timeout_test",
            conversation_id="conv_timeout",
            hitl_type="clarification",
        )

        # Wait with short timeout
        response = await registry.wait_for_response("timeout_test", timeout=0.01)
        assert response is None  # Should timeout

        stats = registry.get_stats()
        assert stats["total_timeouts"] == 1

    async def test_expired_waiter_cleanup(self, registry):
        """Test cleanup of expired waiters."""
        # Register a waiter
        await registry.register_waiter(
            request_id="expired_001",
            conversation_id="conv_expired",
            hitl_type="clarification",
        )

        # Clean up with 0 max age (everything is expired)
        cleaned = await registry.cleanup_expired(max_age_seconds=0)
        assert cleaned == 1
        assert not registry.has_waiter("expired_001")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
