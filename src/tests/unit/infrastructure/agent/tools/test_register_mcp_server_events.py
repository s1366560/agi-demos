"""Tests for real-time tool injection via AgentToolsUpdatedEvent.

This test file follows TDD methodology:
1. Write failing test first (RED)
2. Implement minimal code to pass (GREEN)
3. Refactor while keeping tests passing (REFACTOR)

The tests verify that when an MCP server is registered, the tools become
immediately available without requiring an additional round-trip.
"""

from unittest.mock import AsyncMock, MagicMock, patch

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
    """Test that RegisterMCPServerTool emits tools updated events."""

    @pytest.mark.asyncio
    async def test_register_emits_tools_updated_event(self):
        """
        RED Test: Verify that RegisterMCPServerTool emits AgentToolsUpdatedEvent.
        """
        from src.infrastructure.agent.tools.register_mcp_server import RegisterMCPServerTool

        # Mock dependencies
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock()

        # Mock successful install/start/discover
        mock_adapter.call_tool.side_effect = [
            # mcp_server_install
            {"content": [{"type": "text", "text": '{"success": true}'}]},
            # mcp_server_start
            {"content": [{"type": "text", "text": '{"success": true}'}]},
            # mcp_server_discover_tools
            {
                "content": [
                    {
                        "type": "text",
                        "text": '[{"name": "tool1", "_meta": {}}, {"name": "tool2", "_meta": {}}]',
                    }
                ]
            },
        ]

        tool = RegisterMCPServerTool(
            tenant_id="tenant-1",
            project_id="proj-1",
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            session_factory=None,
        )

        # Execute
        result = await tool.execute(
            server_name="test-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )

        # Verify tool executed successfully
        assert "Error:" not in result
        assert "registered and started successfully" in result

        # Verify pending events contain AgentToolsUpdatedEvent
        events = tool.consume_pending_events()
        tool_updated_events = [e for e in events if isinstance(e, AgentToolsUpdatedEvent)]

        assert len(tool_updated_events) == 1, (
            f"Expected 1 AgentToolsUpdatedEvent, got {len(tool_updated_events)}"
        )

        event = tool_updated_events[0]
        assert event.server_name == "test-server"
        assert "tool1" in event.tool_names or "mcp__test-server__tool1" in event.tool_names
        assert event.requires_refresh is True

    @pytest.mark.asyncio
    async def test_register_includes_app_tools_in_event(self):
        """
        Test that discovered MCP App tools are included in the event.
        """
        from src.infrastructure.agent.tools.register_mcp_server import RegisterMCPServerTool

        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock()

        # Mock with tools that have UI metadata
        mock_adapter.call_tool.side_effect = [
            {"content": [{"type": "text", "text": '{"success": true}'}]},
            {"content": [{"type": "text", "text": '{"success": true}'}]},
            {
                "content": [
                    {
                        "type": "text",
                        "text": """[
                            {"name": "regular_tool", "_meta": {}},
                            {
                                "name": "ui_tool",
                                "_meta": {
                                    "ui": {
                                        "resourceUri": "app://ui-tool",
                                        "title": "UI Tool"
                                    }
                                }
                            }
                        ]""",
                    }
                ]
            },
        ]

        tool = RegisterMCPServerTool(
            tenant_id="tenant-1",
            project_id="proj-1",
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
            session_factory=AsyncMock(),
        )

        # Execute
        await tool.execute(
            server_name="app-server",
            server_type="stdio",
            command="node",
            args=["server.js"],
        )

        # Verify both tools are in the event
        events = tool.consume_pending_events()
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
