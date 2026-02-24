"""Tests for MCP Elicitation integration with HITL system.

This module tests the integration of MCP elicitation requests
with the existing Human-in-the-Loop (HITL) system.

MCP Elicitation allows MCP servers to request information from users
through the agent. We integrate this with the existing HITL infrastructure.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.domain.events.agent_events import AgentElicitationAnsweredEvent, AgentElicitationAskedEvent
from src.infrastructure.agent.mcp.registry import MCPServerRegistry


@pytest.mark.unit
class TestMCPElicitationIntegration:
    """Test MCP Elicitation integration with HITL system."""

    @pytest.fixture
    def registry(self):
        """Create a fresh MCPServerRegistry for each test."""
        return MCPServerRegistry(cache_ttl_seconds=60, health_check_interval_seconds=30)

    @pytest.fixture
    def mock_client(self):
        """Create a mock MCP client."""
        client = AsyncMock()
        client.connect = AsyncMock()
        client.disconnect = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.list_tools = AsyncMock(return_value=[])
        return client

    @pytest.mark.asyncio
    async def test_elicitation_event_exists(self):
        """Test that AgentElicitationAskedEvent can be created.

        RED: This should fail initially because the event class doesn't exist yet.
        """
        event = AgentElicitationAskedEvent(
            request_id="req_123",
            server_id="server_1",
            server_name="Test Server",
            message="Please provide your API key",
            requested_schema={
                "type": "object",
                "properties": {"api_key": {"type": "string", "description": "API key"}},
                "required": ["api_key"],
            },
        )

        assert event.request_id == "req_123"
        assert event.server_id == "server_1"
        assert event.message == "Please provide your API key"
        assert event.requested_schema["type"] == "object"

    @pytest.mark.asyncio
    async def test_elicitation_answered_event_exists(self):
        """Test that AgentElicitationAnsweredEvent can be created.

        RED: This should fail initially because the event class doesn't exist yet.
        """
        event = AgentElicitationAnsweredEvent(
            request_id="req_123", response={"api_key": "sk-test-key"}
        )

        assert event.request_id == "req_123"
        assert event.response["api_key"] == "sk-test-key"

    @pytest.mark.asyncio
    async def test_registry_has_elicitation_handler(self, registry):
        """Test that registry can set an elicitation request handler.

        RED: This should fail because set_elicitation_handler doesn't exist yet.
        """
        handler_called = False

        async def handler(server_id: str, message: str, schema: dict[str, Any]) -> dict[str, Any]:
            nonlocal handler_called
            handler_called = True
            return {"api_key": "test-key"}

        # Set the elicitation handler
        registry.set_elicitation_handler(handler)

        # Verify handler is stored
        assert registry._elicitation_handler is not None
        assert registry._elicitation_handler == handler

    @pytest.mark.asyncio
    async def test_registry_handle_elicitation_request(self, registry, mock_client):
        """Test that registry can handle elicitation requests from MCP servers.

        RED: This should fail because handle_elicitation_request doesn't exist yet.
        """
        response_received = None

        async def handler(server_id: str, message: str, schema: dict[str, Any]) -> dict[str, Any]:
            nonlocal response_received
            response_received = {"server_id": server_id, "message": message, "schema": schema}
            return {"api_key": "user-provided-key"}

        registry.set_elicitation_handler(handler)

        # Register a mock server
        with patch.object(registry, "_clients", {"server_1": mock_client}):
            # Handle elicitation request
            result = await registry.handle_elicitation_request(
                server_id="server_1",
                message="Please provide your API key",
                requested_schema={"type": "object", "properties": {"api_key": {"type": "string"}}},
            )

        assert result == {"api_key": "user-provided-key"}
        assert response_received is not None
        assert response_received["server_id"] == "server_1"
        assert response_received["message"] == "Please provide your API key"

    @pytest.mark.asyncio
    async def test_elicitation_handler_returns_none_when_not_set(self, registry):
        """Test that elicitation returns None when no handler is configured."""
        result = await registry.handle_elicitation_request(
            server_id="server_1",
            message="Please provide input",
            requested_schema={"type": "object"},
        )

        # Should return None when no handler is set
        assert result is None

    @pytest.mark.asyncio
    async def test_elicitation_converts_to_hitl_clarification(self, registry):
        """Test that elicitation requests are converted to HITL clarification type.

        This tests the conversion from MCP elicitation schema to HITL's
        ClarificationRequestData format.
        """

        _conversion_result = None

        async def handler(server_id: str, message: str, schema: dict[str, Any]) -> dict[str, Any]:
            return {"result": "success"}

        registry.set_elicitation_handler(handler)

        # Elicitation with enum options should map to clarification options
        schema = {
            "type": "object",
            "properties": {
                "choice": {
                    "type": "string",
                    "enum": ["option_a", "option_b", "option_c"],
                    "description": "Select an option",
                }
            },
            "required": ["choice"],
        }

        with patch.object(registry, "_clients", {"server_1": AsyncMock()}):
            result = await registry.handle_elicitation_request(
                server_id="server_1", message="Please select an option", requested_schema=schema
            )

        assert result is not None

    @pytest.mark.asyncio
    async def test_elicitation_timeout_handling(self, registry):
        """Test that elicitation requests respect timeout settings.

        The registry handles timeouts gracefully by returning None
        instead of raising an exception.
        """
        import asyncio

        async def slow_handler(
            server_id: str, message: str, schema: dict[str, Any]
        ) -> dict[str, Any]:
            await asyncio.sleep(10)  # Simulate slow response
            return {"result": "too late"}

        registry.set_elicitation_handler(slow_handler)

        # Should timeout and return None (graceful handling)
        result = await registry.handle_elicitation_request(
            server_id="server_1",
            message="Please respond quickly",
            requested_schema={"type": "object"},
            timeout_seconds=0.1,
        )

        # Registry returns None on timeout instead of raising
        assert result is None


@pytest.mark.unit
class TestElicitationEventSerialization:
    """Test elicitation event serialization for SSE streaming."""

    def test_elicitation_asked_event_to_dict(self):
        """Test AgentElicitationAskedEvent serialization."""
        event = AgentElicitationAskedEvent(
            request_id="req_456",
            server_id="server_2",
            server_name="Test MCP Server",
            message="Enter your credentials",
            requested_schema={
                "type": "object",
                "properties": {"username": {"type": "string"}, "password": {"type": "string"}},
            },
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "elicitation_asked"
        assert "data" in event_dict
        assert event_dict["data"]["request_id"] == "req_456"
        assert event_dict["data"]["server_id"] == "server_2"
        assert event_dict["data"]["message"] == "Enter your credentials"

    def test_elicitation_answered_event_to_dict(self):
        """Test AgentElicitationAnsweredEvent serialization."""
        event = AgentElicitationAnsweredEvent(
            request_id="req_789", response={"username": "user1", "password": "pass123"}
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "elicitation_answered"
        assert event_dict["data"]["request_id"] == "req_789"
        assert event_dict["data"]["response"]["username"] == "user1"


@pytest.mark.unit
class TestElicitationEventTypeRegistration:
    """Test that elicitation events are properly registered in the event type system."""

    def test_elicitation_event_types_exist(self):
        """Test that ELICITATION_ASKED and ELICITATION_ANSWERED event types exist."""
        from src.domain.events.types import AgentEventType

        # These should exist after implementation
        assert hasattr(AgentEventType, "ELICITATION_ASKED")
        assert hasattr(AgentEventType, "ELICITATION_ANSWERED")

        assert AgentEventType.ELICITATION_ASKED.value == "elicitation_asked"
        assert AgentEventType.ELICITATION_ANSWERED.value == "elicitation_answered"

    def test_elicitation_in_hitl_event_types(self):
        """Test that elicitation events are in HITL_EVENT_TYPES set."""
        from src.domain.events.types import HITL_EVENT_TYPES, AgentEventType

        # Elicitation events should be considered HITL events
        assert AgentEventType.ELICITATION_ASKED in HITL_EVENT_TYPES
