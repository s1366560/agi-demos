"""
Integration tests for MCP tool integration in Agent Worker.

Tests cover:
- MCP Temporal Adapter initialization
- MCP tools loading through the full stack
- MCP tools being available in ReActAgent
"""

from unittest.mock import AsyncMock, Mock

import pytest

from src.infrastructure.adapters.secondary.temporal.agent_worker_state import (
    _mcp_temporal_adapter,
    get_or_create_tools,
    set_mcp_temporal_adapter,
)


class TestMCPAdapterInitialization:
    """Test MCP Temporal Adapter initialization in Agent Worker."""

    @pytest.mark.asyncio
    async def test_get_or_create_tools_without_mcp_adapter(self):
        """Test that get_or_create_tools works when MCP adapter is not initialized."""
        # Ensure MCP adapter is None
        global _mcp_temporal_adapter
        original_adapter = _mcp_temporal_adapter
        _mcp_temporal_adapter = None

        try:
            # Create mock dependencies
            mock_graph_service = Mock()
            mock_graph_service.neo4j_client = Mock()
            mock_redis_client = AsyncMock()
            mock_redis_client.ping = AsyncMock(return_value=True)

            # Get tools - should work without MCP adapter
            tools = await get_or_create_tools(
                project_id="test-project",
                tenant_id="test-tenant",
                graph_service=mock_graph_service,
                redis_client=mock_redis_client,
            )

            # Should have built-in tools and skill_loader, but no MCP tools
            assert "web_search" in tools
            assert "web_scrape" in tools
            assert "skill_loader" in tools

            # No MCP tools since adapter is None
            mcp_tools = {k: v for k, v in tools.items() if k.startswith("mcp__")}
            assert len(mcp_tools) == 0

        finally:
            # Restore original adapter
            _mcp_temporal_adapter = original_adapter

    @pytest.mark.asyncio
    async def test_get_or_create_tools_with_mock_mcp_adapter(self):
        """Test that get_or_create_tools loads MCP tools when adapter is available."""
        from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPToolInfo

        # Create mock MCP adapter
        mock_mcp_adapter = AsyncMock()
        mock_mcp_adapter.list_all_tools = AsyncMock(
            return_value=[
                MCPToolInfo(
                    name="mcp__test_server__test_tool",
                    server_name="test_server",
                    description="Test MCP tool",
                    input_schema={"type": "object", "properties": {}, "required": []},
                )
            ]
        )

        # Set the adapter
        set_mcp_temporal_adapter(mock_mcp_adapter)

        try:
            # Create mock dependencies
            mock_graph_service = Mock()
            mock_graph_service.neo4j_client = Mock()
            mock_redis_client = AsyncMock()
            mock_redis_client.ping = AsyncMock(return_value=True)

            # Get tools - should include MCP tools
            tools = await get_or_create_tools(
                project_id="test-project",
                tenant_id="test-tenant",
                graph_service=mock_graph_service,
                redis_client=mock_redis_client,
                force_mcp_refresh=True,  # Force refresh to load from adapter
            )

            # Should have built-in tools, skill_loader, and MCP tools
            assert "web_search" in tools
            assert "web_scrape" in tools
            assert "skill_loader" in tools
            assert "mcp__test_server__test_tool" in tools

            # Verify MCP adapter was called
            mock_mcp_adapter.list_all_tools.assert_called_once_with("test-tenant")

        finally:
            # Clear adapter
            set_mcp_temporal_adapter(None)

    @pytest.mark.asyncio
    async def test_get_or_create_tools_handles_mcp_adapter_error(self):
        """Test that get_or_create_tools handles MCP adapter errors gracefully."""
        # Create mock MCP adapter that raises an error
        mock_mcp_adapter = AsyncMock()
        mock_mcp_adapter.list_all_tools = AsyncMock(
            side_effect=Exception("MCP server unavailable")
        )

        # Set the adapter
        set_mcp_temporal_adapter(mock_mcp_adapter)

        try:
            # Create mock dependencies
            mock_graph_service = Mock()
            mock_graph_service.neo4j_client = Mock()
            mock_redis_client = AsyncMock()
            mock_redis_client.ping = AsyncMock(return_value=True)

            # Get tools - should handle error gracefully and return built-in tools
            tools = await get_or_create_tools(
                project_id="test-project",
                tenant_id="test-tenant",
                graph_service=mock_graph_service,
                redis_client=mock_redis_client,
                force_mcp_refresh=True,  # Force refresh to trigger error
            )

            # Should still have built-in tools and skill_loader
            assert "web_search" in tools
            assert "web_scrape" in tools
            assert "skill_loader" in tools

            # No MCP tools due to error
            mcp_tools = {k: v for k, v in tools.items() if k.startswith("mcp__")}
            assert len(mcp_tools) == 0

        finally:
            # Clear adapter
            set_mcp_temporal_adapter(None)


class TestMCPToolsInAgentSession:
    """Test MCP tools in Agent Session context."""

    @pytest.mark.asyncio
    async def test_agent_session_with_mcp_tools(self):
        """Test that Agent Session includes MCP tools in tool_definitions."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            get_or_create_agent_session,
        )
        from src.infrastructure.adapters.secondary.temporal.mcp.adapter import MCPToolInfo
        from src.infrastructure.agent.core.processor import ProcessorConfig

        # Create mock MCP adapter
        mock_mcp_adapter = AsyncMock()
        mock_mcp_adapter.call_mcp_tool = AsyncMock(
            return_value=Mock(
                is_error=False,
                content=[{"type": "text", "text": "Test result"}],
                error_message=None,
            )
        )
        mock_mcp_adapter.list_all_tools = AsyncMock(
            return_value=[
                MCPToolInfo(
                    name="mcp__test_server__read_file",
                    server_name="test_server",
                    description="Read file",
                    input_schema={
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                )
            ]
        )

        # Set the adapter
        set_mcp_temporal_adapter(mock_mcp_adapter)

        try:
            # Create mock dependencies
            mock_graph_service = Mock()
            mock_graph_service.neo4j_client = Mock()
            mock_redis_client = AsyncMock()
            mock_redis_client.ping = AsyncMock(return_value=True)

            # Get tools with MCP
            tools = await get_or_create_tools(
                project_id="test-project",
                tenant_id="test-tenant",
                graph_service=mock_graph_service,
                redis_client=mock_redis_client,
                force_mcp_refresh=True,
            )

            # Create agent session
            processor_config = ProcessorConfig(
                model="test-model",
                api_key="test-key",
                base_url=None,
                temperature=0.7,
                max_tokens=4096,
                max_steps=20,
            )

            session = await get_or_create_agent_session(
                tenant_id="test-tenant",
                project_id="test-project",
                agent_mode="default",
                tools=tools,
                skills=[],
                subagents=[],
                processor_config=processor_config,
            )

            # Verify MCP tool is in session
            tool_names = {td.name for td in session.tool_definitions}
            assert "mcp__test_server__read_file" in tool_names

            # Verify MCP tool is in raw_tools
            assert "mcp__test_server__read_file" in session.raw_tools

        finally:
            # Clear adapter
            set_mcp_temporal_adapter(None)


class TestMCPToolExecution:
    """Test MCP tool execution through ReActAgent."""

    @pytest.mark.asyncio
    async def test_mcp_tool_execute_through_tool_definition(self):
        """Test that MCP tool can be executed through its ToolDefinition wrapper."""
        from src.infrastructure.adapters.secondary.temporal.agent_session_pool import (
            _convert_tools_to_definitions,
        )

        # Create mock MCP adapter
        mock_mcp_adapter = AsyncMock()
        mock_mcp_adapter.call_mcp_tool = AsyncMock(
            return_value=Mock(
                is_error=False,
                content=[
                    {"type": "text", "text": "File content: Hello World"},
                ],
                error_message=None,
            )
        )

        # Create MCP tool adapter
        from dataclasses import dataclass

        from src.infrastructure.mcp.temporal_tool_adapter import MCPTemporalToolAdapter

        @dataclass
        class MockToolInfo:
            name: str
            description: str
            input_schema: dict
            server_name: str

        mcp_tool = MCPTemporalToolAdapter(
            mcp_temporal_adapter=mock_mcp_adapter,
            server_name="filesystem",
            tool_info=MockToolInfo(
                name="read_file",
                description="Read file contents",
                input_schema={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File path"},
                    },
                    "required": ["path"],
                },
                server_name="filesystem",
            ),
            tenant_id="test-tenant",
        )

        # Convert to tool definitions
        tools = {"mcp__filesystem__read_file": mcp_tool}
        definitions = _convert_tools_to_definitions(tools)

        assert len(definitions) == 1
        tool_def = definitions[0]

        # Execute the tool
        result = await tool_def.execute(path="/test/file.txt")

        # Verify result
        assert "Hello World" in result

        # Verify MCP adapter was called correctly
        mock_mcp_adapter.call_mcp_tool.assert_called_once_with(
            tenant_id="test-tenant",
            server_name="filesystem",
            tool_name="read_file",
            arguments={"path": "/test/file.txt"},
        )
