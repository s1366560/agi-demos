"""Unit tests for RegisterMCPServerTool."""

from unittest.mock import AsyncMock, patch

import pytest

from src.infrastructure.agent.tools.register_mcp_server import RegisterMCPServerTool


@pytest.mark.unit
class TestRegisterMCPServerTool:
    """Tests for RegisterMCPServerTool."""

    def _make_tool(self, **kwargs):
        defaults = {
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "sandbox_adapter": None,
            "sandbox_id": None,
            "session_factory": None,
        }
        defaults.update(kwargs)
        return RegisterMCPServerTool(**defaults)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "register_mcp_server"
        assert "MCP server" in tool.description

    def test_parameters_schema(self):
        tool = self._make_tool()
        schema = tool.get_parameters_schema()
        assert "server_name" in schema["properties"]
        assert "server_type" in schema["properties"]
        assert "command" in schema["properties"]
        assert "args" in schema["properties"]
        assert "url" in schema["properties"]
        assert "server_name" in schema["required"]
        assert "server_type" in schema["required"]

    def test_validate_args_stdio(self):
        tool = self._make_tool()
        assert not tool.validate_args()
        assert not tool.validate_args(server_name="test")
        assert not tool.validate_args(server_name="test", server_type="stdio")
        assert tool.validate_args(server_name="test", server_type="stdio", command="node")

    def test_validate_args_sse(self):
        tool = self._make_tool()
        assert not tool.validate_args(server_name="test", server_type="sse")
        assert tool.validate_args(
            server_name="test", server_type="sse", url="http://localhost:3001/sse"
        )

    async def test_execute_no_sandbox(self):
        tool = self._make_tool()
        result = await tool.execute(server_name="my-server", server_type="stdio", command="node")
        assert "Error" in result
        assert "Sandbox not available" in result

    async def test_execute_missing_server_name(self):
        tool = self._make_tool(sandbox_adapter=AsyncMock(), sandbox_id="sb-1")
        result = await tool.execute(server_type="stdio", command="node")
        assert "Error" in result
        assert "server_name is required" in result

    async def test_execute_invalid_server_type(self):
        tool = self._make_tool(sandbox_adapter=AsyncMock(), sandbox_id="sb-1")
        result = await tool.execute(server_name="my-server", server_type="invalid", command="node")
        assert "Error" in result
        assert "Invalid server_type" in result

    async def test_execute_stdio_missing_command(self):
        tool = self._make_tool(sandbox_adapter=AsyncMock(), sandbox_id="sb-1")
        result = await tool.execute(server_name="my-server", server_type="stdio")
        assert "Error" in result
        assert "'command' is required" in result

    async def test_execute_sse_missing_url(self):
        tool = self._make_tool(sandbox_adapter=AsyncMock(), sandbox_id="sb-1")
        result = await tool.execute(server_name="my-server", server_type="sse")
        assert "Error" in result
        assert "'url' is required" in result

    async def test_execute_install_failure(self):
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(
            return_value={
                "content": [
                    {"type": "text", "text": '{"success": false, "error": "pkg not found"}'}
                ]
            }
        )
        tool = self._make_tool(sandbox_adapter=mock_adapter, sandbox_id="sb-1")
        result = await tool.execute(server_name="bad-server", server_type="stdio", command="node")
        assert "Error" in result
        assert "Failed to install" in result

    async def test_execute_start_failure(self):
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # install succeeds
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            else:  # start fails
                return {
                    "content": [
                        {"type": "text", "text": '{"success": false, "error": "port busy"}'}
                    ]
                }

        mock_adapter.call_tool = mock_call_tool
        tool = self._make_tool(sandbox_adapter=mock_adapter, sandbox_id="sb-1")
        result = await tool.execute(server_name="fail-server", server_type="stdio", command="node")
        assert "Error" in result
        assert "Failed to start" in result

    async def test_execute_success_no_apps(self):
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:  # install + start succeed
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            else:  # discover returns tools
                return {
                    "content": [
                        {"type": "text", "text": '[{"name": "query_db", "description": "Run SQL"}]'}
                    ]
                }

        mock_adapter.call_tool = mock_call_tool
        tool = self._make_tool(sandbox_adapter=mock_adapter, sandbox_id="sb-1")
        result = await tool.execute(
            server_name="my-server", server_type="stdio", command="node", args=["server.js"]
        )
        assert "registered and started successfully" in result
        assert "query_db" in result
        assert "MCP App" not in result

    @patch.object(RegisterMCPServerTool, "_persist_app", new_callable=AsyncMock)
    async def test_execute_success_with_apps(self, mock_persist):
        mock_persist.return_value = "test-app-id-123"
        mock_adapter = AsyncMock()
        call_count = 0

        async def mock_call_tool(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                return {"content": [{"type": "text", "text": '{"success": true}'}]}
            else:
                tools = [
                    {
                        "name": "render_dashboard",
                        "_meta": {
                            "ui": {"resourceUri": "ui://dashboard/index.html", "title": "Dashboard"}
                        },
                    },
                    {"name": "query_data", "description": "Query backend"},
                ]
                import json

                return {"content": [{"type": "text", "text": json.dumps(tools)}]}

        mock_adapter.call_tool = mock_call_tool
        tool = self._make_tool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sb-1",
            session_factory=AsyncMock(),
        )
        result = await tool.execute(
            server_name="dashboard-server", server_type="stdio", command="node", args=["server.js"]
        )
        assert "registered and started successfully" in result
        assert "2 tool(s)" in result
        assert "1 MCP App(s)" in result
        assert "render_dashboard" in result

        # Check events - should have AgentMCPAppRegisteredEvent and AgentToolsUpdatedEvent
        events = tool.consume_pending_events()
        assert len(events) >= 2

        # Find the MCP app registered event
        app_events = [e for e in events if hasattr(e, "source")]
        assert len(app_events) == 1
        assert app_events[0].source == "agent_developed"
        assert app_events[0].resource_uri == "ui://dashboard/index.html"

        # Find the tools updated event
        tools_events = [e for e in events if hasattr(e, "tool_names")]
        assert len(tools_events) == 1
        assert "mcp__dashboard-server__render_dashboard" in tools_events[0].tool_names
        toolset_events = [
            e for e in events if isinstance(e, dict) and e.get("type") == "toolset_changed"
        ]
        assert len(toolset_events) == 1

    async def test_execute_exception_handling(self):
        mock_adapter = AsyncMock()
        mock_adapter.call_tool = AsyncMock(side_effect=Exception("Connection lost"))
        tool = self._make_tool(sandbox_adapter=mock_adapter, sandbox_id="sb-1")
        result = await tool.execute(server_name="broken", server_type="stdio", command="node")
        assert "Error" in result
        assert "Connection lost" in result

    def test_set_sandbox_id(self):
        tool = self._make_tool()
        assert tool._sandbox_id is None
        tool.set_sandbox_id("sb-123")
        assert tool._sandbox_id == "sb-123"

    def test_consume_pending_events_empty(self):
        tool = self._make_tool()
        assert tool.consume_pending_events() == []
