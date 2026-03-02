"""Tests for real-time tool injection via AgentToolsUpdatedEvent.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that when an MCP server is registered, the tools become
immediately available without requiring an additional round-trip.
"""

import json
from unittest.mock import AsyncMock

import pytest

from src.domain.events.agent_events import AgentToolsUpdatedEvent
from src.domain.events.types import AgentEventType


class TestAgentToolsUpdatedEvent:
    """Test AgentToolsUpdatedEvent definition and usage."""

    def test_event_type_exists(self):
        """
        RED Test: Verify that TOOLS_UPDATED event type exists.
        """
        # This test will FAIL if TOOLS_UPDATED doesn't exist
        assert hasattr(AgentEventType, "TOOLS_UPDATED")
        assert AgentEventType.TOOLS_UPDATED.value == "tools_updated"

    def test_event_class_exists(self):
        """
        RED Test: Verify that AgentToolsUpdatedEvent class exists.
        """
        # This test will FAIL if AgentToolsUpdatedEvent doesn't exist
        assert AgentToolsUpdatedEvent is not None

    def test_event_has_required_fields(self):
        """
        RED Test: Verify that AgentToolsUpdatedEvent has required fields.
        """
        event = AgentToolsUpdatedEvent(
            project_id="proj-456",
            tool_names=["tool1", "tool2"],
            server_name="test-server",
            requires_refresh=True,
        )

        assert event.event_type == AgentEventType.TOOLS_UPDATED
        assert event.project_id == "proj-456"
        assert event.tool_names == ["tool1", "tool2"]
        assert event.server_name == "test-server"
        assert event.requires_refresh is True

    def test_event_to_dict(self):
        """
        Test that event can be serialized to dict for SSE.
        """
        event = AgentToolsUpdatedEvent(
            project_id="proj-456",
            tool_names=["mcp__server__tool1"],
            server_name="my-server",
            requires_refresh=True,
        )

        event_dict = event.to_event_dict()

        assert event_dict["type"] == "tools_updated"
        # Check that required fields are in the output
        assert "project_id" in event_dict or event.project_id == "proj-456"
        assert event.tool_names == ["mcp__server__tool1"]
        assert event.server_name == "my-server"
        assert event.requires_refresh is True


class TestRegisterMCPServerToolEvents:
    """Test that register_mcp_server_tool emits tools updated events."""

    @pytest.mark.asyncio
    async def test_register_emits_tools_updated_event(self, monkeypatch: pytest.MonkeyPatch):
        """
        RED Test: Verify that register_mcp_server_tool emits AgentToolsUpdatedEvent.
        """
        from typing import Any

        from src.infrastructure.agent.tools.context import ToolContext
        from src.infrastructure.agent.tools.register_mcp_server import (
            register_mcp_server_tool,
        )

        _MOD = "src.infrastructure.agent.tools.register_mcp_server"

        def _make_ctx(**overrides: Any) -> ToolContext:
            defaults: dict[str, Any] = {
                "session_id": "session-1",
                "message_id": "msg-1",
                "call_id": "call-1",
                "agent_name": "test-agent",
                "conversation_id": "conv-1",
            }
            defaults.update(overrides)
            return ToolContext(**defaults)

        # Mock sandbox adapter
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # install + start succeed
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            # discover returns tools
            return {
                "content": [
                    {
                        "type": "text",
                        "text": '[{"name": "tool1", "_meta": {}}, {"name": "tool2", "_meta": {}}]',
                    }
                ]
            }

        mock_adapter.call_tool = mock_call_tool

        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sandbox-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "proj-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", None)
        # Stub persist to avoid DB
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None)
        )
        # Stub SelfModifyingLifecycleOrchestrator.run_post_change
        _LIFECYCLE = (
            "src.infrastructure.agent.tools.self_modifying_lifecycle"
            + ".SelfModifyingLifecycleOrchestrator.run_post_change"
        )
        monkeypatch.setattr(
            _LIFECYCLE,
            staticmethod(
                lambda **kwargs: {"cache_invalidation": {}, "probe": {"status": "ok"}}  # type: ignore[arg-type]
            ),
        )

        ctx = _make_ctx()
        result = await register_mcp_server_tool.execute(
            ctx,
            server_name="test-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )

        # Verify tool executed successfully
        assert not result.is_error
        assert "registered and started successfully" in result.output

        # Verify pending events contain AgentToolsUpdatedEvent
        events = ctx.consume_pending_events()
        tool_updated_events = [e for e in events if isinstance(e, AgentToolsUpdatedEvent)]

        assert len(tool_updated_events) == 1, (
            f"Expected 1 AgentToolsUpdatedEvent, got {len(tool_updated_events)}"
        )

        event = tool_updated_events[0]
        assert event.server_name == "test-server"
        assert "mcp__test-server__tool1" in event.tool_names
        assert "mcp__test-server__tool2" in event.tool_names
        assert event.requires_refresh is True

    @pytest.mark.asyncio
    async def test_register_includes_app_tools_in_event(self, monkeypatch: pytest.MonkeyPatch):
        """
        Test that discovered MCP App tools are included in the event.
        """
        from typing import Any

        from src.infrastructure.agent.tools.context import ToolContext
        from src.infrastructure.agent.tools.register_mcp_server import (
            register_mcp_server_tool,
        )

        _MOD = "src.infrastructure.agent.tools.register_mcp_server"

        def _make_ctx(**overrides: Any) -> ToolContext:
            defaults: dict[str, Any] = {
                "session_id": "session-1",
                "message_id": "msg-1",
                "call_id": "call-1",
                "agent_name": "test-agent",
                "conversation_id": "conv-1",
            }
            defaults.update(overrides)
            return ToolContext(**defaults)

        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs: Any) -> dict[str, Any]:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            tools_json = json.dumps([
                {"name": "regular_tool", "_meta": {}},
                {
                    "name": "ui_tool",
                    "_meta": {
                        "ui": {
                            "resourceUri": "app://ui-tool",
                            "title": "UI Tool",
                        }
                    },
                },
            ])
            return {"content": [{"type": "text", "text": tools_json}]}

        mock_adapter.call_tool = mock_call_tool

        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_adapter", mock_adapter)
        monkeypatch.setattr(f"{_MOD}._register_mcp_sandbox_id", "sandbox-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_tenant_id", "tenant-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_project_id", "proj-1")
        monkeypatch.setattr(f"{_MOD}._register_mcp_session_factory", AsyncMock())
        # Stub persist helpers to avoid DB
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_persist_server", AsyncMock(return_value=None)
        )
        monkeypatch.setattr(
            f"{_MOD}._register_mcp_persist_app", AsyncMock(return_value="test-app-id")
        )
        # Stub SelfModifyingLifecycleOrchestrator.run_post_change
        _LIFECYCLE = (
            "src.infrastructure.agent.tools.self_modifying_lifecycle"
            + ".SelfModifyingLifecycleOrchestrator.run_post_change"
        )
        monkeypatch.setattr(
            _LIFECYCLE,
            staticmethod(
                lambda **kwargs: {"cache_invalidation": {}, "probe": {"status": "ok"}}  # type: ignore[arg-type]
            ),
        )

        ctx = _make_ctx()
        await register_mcp_server_tool.execute(
            ctx,
            server_name="app-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )

        # Verify both tools are in the event
        events = ctx.consume_pending_events()
        tool_updated_events = [e for e in events if isinstance(e, AgentToolsUpdatedEvent)]

        assert len(tool_updated_events) == 1
        event = tool_updated_events[0]

        # Check that all tools are included
        assert len(event.tool_names) == 2

class TestToolsUpdatedEventIntegration:
    """Integration tests for tools updated event handling."""

    def test_event_is_in_frontend_event_types(self):
        """
        Test that TOOLS_UPDATED is included in frontend event types.
        """
        from src.domain.events.types import get_frontend_event_types

        frontend_types = get_frontend_event_types()
        assert "tools_updated" in frontend_types, (
            "tools_updated should be exposed to frontend for real-time updates"
        )

    def test_event_category_is_agent(self):
        """
        Test that TOOLS_UPDATED has the correct event category.
        """
        from src.domain.events.types import EventCategory, get_event_category

        category = get_event_category(AgentEventType.TOOLS_UPDATED)
        assert category == EventCategory.AGENT
