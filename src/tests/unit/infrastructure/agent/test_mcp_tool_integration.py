"""
Unit tests for MCP tool integration in ReActAgent.

Tests cover:
- MCP tools being properly loaded and converted to ToolDefinition
- MCP tools being included in the agent session pool
- MCP tools being executable through the ReActAgent
"""

from dataclasses import dataclass
from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
    _convert_tools_to_definitions,
    compute_tools_hash,
)
from src.infrastructure.agent.tools.base import AgentTool
from src.infrastructure.mcp.tool_adapter import MCPToolAdapter as MCPTemporalToolAdapter


@dataclass
class MockMCPToolInfo:
    """Mock MCP tool info dataclass."""

    name: str
    description: str
    input_schema: dict
    server_name: str


class MockBuiltInTool(AgentTool):
    """Mock built-in tool for testing."""

    def __init__(
        self,
        name: str = "builtin_tool",
        description: str = "Built-in tool description",
    ):
        super().__init__(name=name, description=description)

    async def execute(self, **kwargs):
        return f"Builtin executed with: {kwargs}"


class TestMCPToolIntegration:
    """Test MCP tool integration in ReActAgent."""

    def test_compute_tools_hash_with_mcp_tools(self):
        """Test that tools hash is computed correctly with MCP tools."""
        mcp_adapter_mock = AsyncMock()

        # Create a mock MCP tool with proper dataclass structure
        mcp_tool = MCPTemporalToolAdapter(
            mcp_adapter=mcp_adapter_mock,
            server_name="test_server",
            tool_info=MockMCPToolInfo(
                name="mcp__test_server__test_tool",
                description="MCP tool from test server",
                input_schema={"type": "object", "properties": {}, "required": []},
                server_name="test_server",
            ),
            tenant_id="tenant-1",
        )

        tools = {
            "builtin_tool": MockBuiltInTool(),
            "mcp__test_server__test_tool": mcp_tool,
        }

        hash_value = compute_tools_hash(tools)

        assert hash_value is not None
        assert isinstance(hash_value, str)
        assert len(hash_value) > 0

    def test_convert_tools_to_definitions_includes_mcp_tools(self):
        """Test that MCP tools are converted to ToolDefinition correctly."""
        mcp_adapter_mock = AsyncMock()
        mcp_adapter_mock.call_mcp_tool = AsyncMock(
            return_value=Mock(
                is_error=False,
                content=[{"type": "text", "text": "Test result"}],
                error_message=None,
            )
        )

        mcp_tool = MCPTemporalToolAdapter(
            mcp_adapter=mcp_adapter_mock,
            server_name="test_server",
            tool_info=MockMCPToolInfo(
                name="mcp__test_server__read_file",
                description="Read a file from the filesystem",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
                server_name="test_server",
            ),
            tenant_id="tenant-1",
        )

        tools = {
            "builtin_tool": MockBuiltInTool(),
            "mcp__test_server__read_file": mcp_tool,
        }

        definitions = _convert_tools_to_definitions(tools)

        # Should have 2 tool definitions
        assert len(definitions) == 2

        # Check that both tools are present
        tool_names = {d.name for d in definitions}
        assert "builtin_tool" in tool_names
        assert "mcp__test_server__read_file" in tool_names

    @pytest.mark.asyncio
    async def test_mcp_tool_execute_wrapper_is_async(self):
        """Test that MCP tool execute wrapper is properly async."""
        mcp_adapter_mock = AsyncMock()
        mcp_adapter_mock.call_mcp_tool = AsyncMock(
            return_value=Mock(
                is_error=False,
                content=[{"type": "text", "text": "File content"}],
                error_message=None,
            )
        )

        mcp_tool = MCPTemporalToolAdapter(
            mcp_adapter=mcp_adapter_mock,
            server_name="test_server",
            tool_info=MockMCPToolInfo(
                name="read_file",
                description="Read a file",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                    },
                    "required": ["path"],
                },
                server_name="test_server",
            ),
            tenant_id="tenant-1",
        )

        tools = {
            "mcp__test_server__read_file": mcp_tool,
        }

        definitions = _convert_tools_to_definitions(tools)

        assert len(definitions) == 1
        tool_def = definitions[0]

        # Verify execute is a coroutine function
        import inspect

        assert inspect.iscoroutinefunction(tool_def.execute)

        # Execute the tool
        result = await tool_def.execute(path="/test/file.txt")

        # Verify result
        assert "File content" in result

    def test_convert_mcp_tool_with_different_execute_methods(self):
        """Test that tools with different execute method signatures are handled."""
        # Test tool with execute method that returns awaitable
        class AwaitableTool(AgentTool):
            def __init__(self):
                super().__init__(name="awaitable_tool", description="Tool with async execute")

            async def execute(self, **kwargs):
                return "async result"

        # Test tool with execute method that returns non-awaitable
        class SyncTool(AgentTool):
            def __init__(self):
                super().__init__(name="sync_tool", description="Tool with sync execute")

            def execute(self, **kwargs):
                return "sync result"

        tools = {
            "awaitable_tool": AwaitableTool(),
            "sync_tool": SyncTool(),
        }

        definitions = _convert_tools_to_definitions(tools)

        assert len(definitions) == 2

    def test_mcp_tool_parameters_schema_is_preserved(self):
        """Test that MCP tool parameter schema is preserved correctly."""
        mcp_adapter_mock = AsyncMock()

        mcp_tool = MCPTemporalToolAdapter(
            mcp_adapter=mcp_adapter_mock,
            server_name="test_server",
            tool_info=MockMCPToolInfo(
                name="complex_tool",
                description="Tool with complex parameters",
                input_schema={
                    "type": "object",
                    "properties": {
                        "url": {
                            "type": "string",
                            "description": "The URL to fetch",
                        },
                        "method": {
                            "type": "string",
                            "enum": ["GET", "POST"],
                            "default": "GET",
                        },
                        "headers": {
                            "type": "object",
                            "description": "HTTP headers",
                        },
                    },
                    "required": ["url"],
                },
                server_name="test_server",
            ),
            tenant_id="tenant-1",
        )

        tools = {"mcp__test_server__complex_tool": mcp_tool}
        definitions = _convert_tools_to_definitions(tools)

        assert len(definitions) == 1
        tool_def = definitions[0]

        # Check parameter schema
        assert tool_def.parameters["type"] == "object"
        assert "url" in tool_def.parameters["properties"]
        assert "method" in tool_def.parameters["properties"]
        assert "headers" in tool_def.parameters["properties"]
        assert tool_def.parameters["required"] == ["url"]


class TestAgentSessionPoolMCPIntegration:
    """Test Agent Session Pool integration with MCP tools."""

    @pytest.mark.asyncio
    async def test_mcp_tools_in_session_context(self):
        """Test that MCP tools are included in session context."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            AgentSessionContext,
        )

        # Create mock tools including MCP tools
        mcp_adapter_mock = AsyncMock()
        mcp_tool = MCPTemporalToolAdapter(
            mcp_adapter=mcp_adapter_mock,
            server_name="test_server",
            tool_info=MockMCPToolInfo(
                name="test_tool",
                description="Test MCP tool",
                input_schema={"type": "object", "properties": {}, "required": []},
                server_name="test_server",
            ),
            tenant_id="tenant-1",
        )

        tools = {
            "builtin_tool": MockBuiltInTool(),
            "mcp__test_server__test_tool": mcp_tool,
        }

        tool_definitions = _convert_tools_to_definitions(tools)

        # Create session context
        session = AgentSessionContext(
            session_key="tenant-1:project-1:default",
            tenant_id="tenant-1",
            project_id="project-1",
            agent_mode="default",
            tool_definitions=tool_definitions,
            raw_tools=tools,
        )

        # Verify both tools are in tool_definitions
        assert len(session.tool_definitions) == 2
        tool_names = {td.name for td in session.tool_definitions}
        assert "builtin_tool" in tool_names
        assert "mcp__test_server__test_tool" in tool_names

        # Verify raw_tools also has both
        assert len(session.raw_tools) == 2
        assert "builtin_tool" in session.raw_tools
        assert "mcp__test_server__test_tool" in session.raw_tools
