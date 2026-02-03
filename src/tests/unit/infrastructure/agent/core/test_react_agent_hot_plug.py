"""Tests for ReActAgent hot-plug functionality.

Tests that tools can be added/removed dynamically at runtime
without restarting the agent.
"""

from typing import Any, Dict

import pytest

from src.infrastructure.agent.core.react_agent import ReActAgent


class MockTool:
    """Simple mock tool for testing."""

    def __init__(self, name: str, description: str = "A mock tool"):
        self.name = name
        self.description = description

    async def execute(self, **kwargs) -> str:
        return f"Executed {self.name}"

    def get_parameters_schema(self) -> Dict[str, Any]:
        return {"type": "object", "properties": {}, "required": []}


class TestReActAgentHotPlug:
    """Tests for hot-plug tool functionality."""

    def test_agent_with_static_tools(self):
        """Should work with static tools dict (backward compatibility)."""
        tools = {
            "tool1": MockTool("tool1", "First tool"),
            "tool2": MockTool("tool2", "Second tool"),
        }

        agent = ReActAgent(
            model="test-model",
            tools=tools,
        )

        raw_tools, tool_defs = agent._get_current_tools()
        assert len(tool_defs) == 2
        assert raw_tools == tools
        assert not agent._use_dynamic_tools

    def test_agent_with_tool_provider(self):
        """Should use tool_provider for dynamic tools."""
        call_count = 0

        def provide_tools() -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            # Return different tools based on call count
            if call_count <= 1:
                return {"tool1": MockTool("tool1")}
            else:
                return {
                    "tool1": MockTool("tool1"),
                    "tool2": MockTool("tool2"),
                }

        agent = ReActAgent(
            model="test-model",
            tool_provider=provide_tools,
        )

        assert agent._use_dynamic_tools

        # First call - should get 1 tool
        raw_tools1, defs1 = agent._get_current_tools()
        assert len(defs1) == 1
        assert call_count == 1

        # Second call - should get 2 tools (hot-plugged)
        raw_tools2, defs2 = agent._get_current_tools()
        assert len(defs2) == 2
        assert call_count == 2

    def test_tool_provider_called_each_time(self):
        """Should call tool_provider on each _get_current_tools() call."""
        call_count = 0

        def counting_provider() -> Dict[str, Any]:
            nonlocal call_count
            call_count += 1
            return {"tool1": MockTool("tool1")}

        agent = ReActAgent(
            model="test-model",
            tool_provider=counting_provider,
        )

        # Multiple calls should increment counter
        agent._get_current_tools()
        agent._get_current_tools()
        agent._get_current_tools()

        assert call_count == 3

    def test_validation_requires_tools_or_provider(self):
        """Should raise error if no tools or provider specified."""
        with pytest.raises(ValueError) as exc_info:
            ReActAgent(model="test-model")

        assert "tools" in str(exc_info.value).lower() or "tool_provider" in str(exc_info.value).lower()

    def test_cached_tools_take_precedence(self):
        """Should use cached tool definitions if provided (Session Pool)."""
        from src.infrastructure.agent.processor.processor import ToolDefinition

        cached_defs = [
            ToolDefinition(
                name="cached_tool",
                description="A cached tool",
                parameters={},
                execute=lambda **kwargs: "cached result",
            )
        ]

        agent = ReActAgent(
            model="test-model",
            _cached_tool_definitions=cached_defs,
        )

        assert not agent._use_dynamic_tools
        raw_tools, defs = agent._get_current_tools()
        assert len(defs) == 1
        assert defs[0].name == "cached_tool"

    def test_tool_conversion_from_dict(self):
        """Should correctly convert tools dict to ToolDefinitions."""
        tools = {
            "test_tool": MockTool("test_tool", "A test description"),
        }

        agent = ReActAgent(
            model="test-model",
            tools=tools,
        )

        _, defs = agent._get_current_tools()
        assert len(defs) == 1
        assert defs[0].name == "test_tool"
        assert defs[0].description == "A test description"

    def test_empty_tool_provider_result(self):
        """Should handle empty tools from provider gracefully."""
        def empty_provider() -> Dict[str, Any]:
            return {}

        agent = ReActAgent(
            model="test-model",
            tool_provider=empty_provider,
        )

        raw_tools, defs = agent._get_current_tools()
        assert len(defs) == 0
        assert raw_tools == {}


class TestHotPlugScenarios:
    """Real-world hot-plug scenarios."""

    def test_add_tool_at_runtime(self):
        """Simulate adding a tool at runtime."""
        registered_tools: Dict[str, Any] = {
            "builtin_tool": MockTool("builtin_tool", "Always available"),
        }

        def dynamic_provider() -> Dict[str, Any]:
            return registered_tools.copy()

        agent = ReActAgent(
            model="test-model",
            tool_provider=dynamic_provider,
        )

        # Initially 1 tool
        _, defs1 = agent._get_current_tools()
        assert len(defs1) == 1

        # Hot-plug: add new tool
        registered_tools["new_tool"] = MockTool("new_tool", "Newly added")

        # Now 2 tools
        _, defs2 = agent._get_current_tools()
        assert len(defs2) == 2
        tool_names = [d.name for d in defs2]
        assert "new_tool" in tool_names

    def test_remove_tool_at_runtime(self):
        """Simulate removing a tool at runtime."""
        registered_tools: Dict[str, Any] = {
            "tool1": MockTool("tool1"),
            "tool2": MockTool("tool2"),
        }

        def dynamic_provider() -> Dict[str, Any]:
            return registered_tools.copy()

        agent = ReActAgent(
            model="test-model",
            tool_provider=dynamic_provider,
        )

        # Initially 2 tools
        _, defs1 = agent._get_current_tools()
        assert len(defs1) == 2

        # Hot-unplug: remove tool
        del registered_tools["tool2"]

        # Now 1 tool
        _, defs2 = agent._get_current_tools()
        assert len(defs2) == 1
        assert defs2[0].name == "tool1"

    def test_mcp_tool_integration_simulation(self):
        """Simulate MCP server tools being hot-plugged."""
        builtin_tools = {"builtin": MockTool("builtin")}
        mcp_tools: Dict[str, Any] = {}

        def unified_provider() -> Dict[str, Any]:
            # Simulate aggregating builtin + MCP tools
            all_tools = {}
            all_tools.update(builtin_tools)
            all_tools.update(mcp_tools)
            return all_tools

        agent = ReActAgent(
            model="test-model",
            tool_provider=unified_provider,
        )

        # Initially only builtin
        _, defs1 = agent._get_current_tools()
        assert len(defs1) == 1

        # MCP server connects and registers tools
        mcp_tools["mcp_read_file"] = MockTool("mcp_read_file", "MCP: Read a file")
        mcp_tools["mcp_write_file"] = MockTool("mcp_write_file", "MCP: Write a file")

        # Now 3 tools (1 builtin + 2 MCP)
        _, defs2 = agent._get_current_tools()
        assert len(defs2) == 3

        # MCP server disconnects
        mcp_tools.clear()

        # Back to 1 builtin tool
        _, defs3 = agent._get_current_tools()
        assert len(defs3) == 1
