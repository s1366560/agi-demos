"""Unit tests for RegisterAppTool."""

from unittest.mock import AsyncMock, patch

import pytest

from src.domain.model.mcp.app import MCPAppSource
from src.infrastructure.agent.tools.register_app import RegisterAppTool


@pytest.mark.unit
class TestRegisterAppTool:
    """Tests for RegisterAppTool."""

    def _make_tool(self, **kwargs):
        defaults = {
            "tenant_id": "tenant-1",
            "project_id": "project-1",
            "session_factory": None,
            "sandbox_adapter": None,
            "sandbox_id": None,
        }
        defaults.update(kwargs)
        return RegisterAppTool(**defaults)

    def test_name_and_description(self):
        tool = self._make_tool()
        assert tool.name == "register_app"
        assert "interactive HTML" in tool.description

    def test_parameters_schema(self):
        tool = self._make_tool()
        schema = tool.get_parameters_schema()
        assert "title" in schema["properties"]
        assert "html_content" in schema["properties"]
        assert "file_path" in schema["properties"]
        assert "title" in schema["required"]

    def test_validate_args_requires_title(self):
        tool = self._make_tool()
        assert not tool.validate_args()
        assert not tool.validate_args(title="")
        assert not tool.validate_args(title="My App")  # needs html or file
        assert tool.validate_args(title="My App", html_content="<html></html>")
        assert tool.validate_args(title="My App", file_path="/workspace/app.html")

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_execute_inline_html(self, mock_save):
        tool = self._make_tool()
        html = "<html><body><h1>Dashboard</h1></body></html>"
        result = await tool.execute(title="My Dashboard", html_content=html)

        assert "registered successfully" in result
        assert "My Dashboard" in result
        assert tool.has_ui
        assert tool.ui_metadata is not None
        assert "resourceUri" in tool.ui_metadata

    async def test_execute_no_content_error(self):
        tool = self._make_tool()
        result = await tool.execute(title="My App")
        assert "Error" in result
        assert not tool.has_ui

    async def test_execute_oversized_html(self):
        tool = self._make_tool()
        html = "x" * (6 * 1024 * 1024)  # 6MB
        result = await tool.execute(title="Big App", html_content=html)
        assert "Error" in result
        assert "5MB" in result

    async def test_has_ui_false_before_execute(self):
        tool = self._make_tool()
        assert not tool.has_ui
        assert tool.ui_metadata is None

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_has_ui_resets_on_error(self, mock_save):
        tool = self._make_tool()

        # First successful call
        await tool.execute(title="Good", html_content="<html></html>")
        assert tool.has_ui

        # Second call with error (no content)
        result = await tool.execute(title="Bad")
        assert "Error" in result
        assert not tool.has_ui

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_pending_events_emitted(self, mock_save):
        tool = self._make_tool()
        await tool.execute(title="Chart", html_content="<html></html>")

        events = tool.consume_pending_events()
        assert len(events) == 1
        assert events[0].source == "agent_developed"

        # Second consume should be empty
        assert len(tool.consume_pending_events()) == 0

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_execute_reads_sandbox_file(self, mock_save):
        mock_adapter = AsyncMock()
        mock_adapter.execute_tool = AsyncMock(return_value={
            "content": [{"type": "text", "text": "<html><body>From File</body></html>"}]
        })

        tool = self._make_tool(
            sandbox_adapter=mock_adapter,
            sandbox_id="sandbox-1",
        )

        result = await tool.execute(title="File App", file_path="/workspace/app.html")
        assert "registered successfully" in result
        mock_adapter.execute_tool.assert_called_once()

    async def test_execute_sandbox_file_not_found(self):
        mock_adapter = AsyncMock()
        mock_adapter.execute_tool = AsyncMock(side_effect=Exception("File not found"))

        tool = self._make_tool(sandbox_adapter=mock_adapter, sandbox_id="sandbox-1")
        result = await tool.execute(title="Missing", file_path="/workspace/nope.html")
        assert "Error" in result
        assert "Could not read" in result

    async def test_execute_no_session_factory_still_succeeds(self):
        """Tool should still work without DB (just won't persist)."""
        tool = self._make_tool()
        result = await tool.execute(title="Temp App", html_content="<html></html>")
        assert "registered successfully" in result
        assert tool.has_ui

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_app_source_is_agent_developed(self, mock_save):
        tool = self._make_tool()
        await tool.execute(title="Agent App", html_content="<html></html>")

        events = tool.consume_pending_events()
        assert len(events) == 1
        assert events[0].source == MCPAppSource.AGENT_DEVELOPED.value

    def test_set_sandbox_id(self):
        tool = self._make_tool()
        assert tool._sandbox_id is None
        tool.set_sandbox_id("sb-123")
        assert tool._sandbox_id == "sb-123"

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_execute_with_mcp_server_names(self, mock_save):
        """When mcp_server_name/mcp_tool_name provided, use them instead of synthetic names."""
        tool = self._make_tool()
        html = "<html><body>Hello</body></html>"
        result = await tool.execute(
            title="Hello App",
            html_content=html,
            mcp_server_name="mcp-hello-app",
            mcp_tool_name="hello",
        )
        assert "registered successfully" in result
        # Verify the saved app uses actual MCP names
        saved_app = mock_save.call_args[0][0]
        assert saved_app.server_name == "mcp-hello-app"
        assert saved_app.tool_name == "hello"

    @patch.object(RegisterAppTool, "_save_app", new_callable=AsyncMock)
    async def test_execute_without_mcp_names_uses_synthetic(self, mock_save):
        """Without mcp names, generate synthetic names from title."""
        tool = self._make_tool()
        result = await tool.execute(
            title="My Dashboard",
            html_content="<html></html>",
        )
        assert "registered successfully" in result
        saved_app = mock_save.call_args[0][0]
        assert saved_app.server_name == "agent-my-dashboard"
        assert saved_app.tool_name == "app_my_dashboard"

    def test_parameters_schema_includes_mcp_names(self):
        tool = self._make_tool()
        schema = tool.get_parameters_schema()
        assert "mcp_server_name" in schema["properties"]
        assert "mcp_tool_name" in schema["properties"]
