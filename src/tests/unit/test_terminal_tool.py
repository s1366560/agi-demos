"""Unit tests for terminal_tool module-level functions and tool.

Tests the terminal management tool for starting, stopping, and checking
the status of web terminal sessions in sandbox environments.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.result import ToolResult
from src.infrastructure.agent.tools.terminal_tool import (
    TerminalStatus,
    configure_terminal,
    terminal_tool,
)


def _make_ctx() -> ToolContext:
    """Create a minimal ToolContext for testing."""
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )

class TestTerminalTool:
    """Test suite for terminal_tool @tool_define function."""

    @pytest.fixture(autouse=True)
    def _reset_terminal_state(self):
        """Reset module-level terminal state between tests."""
        configure_terminal()
        yield
        configure_terminal()

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    def test_tool_registration_in_registry(self):
        """Test tool has name 'terminal'."""
        assert terminal_tool.name == "terminal"

    def test_tool_description_contains_terminal(self):
        """Test tool has a meaningful description mentioning terminal/ttyd."""
        desc = terminal_tool.description.lower()
        assert "terminal" in desc
        assert "ttyd" in desc or "shell" in desc

    def test_parameters_schema_has_action(self):
        """Test parameters schema defines action enum with start/stop/status."""
        params = terminal_tool.parameters
        assert params["type"] == "object"
        assert "properties" in params
        assert "action" in params["properties"]
        assert params["properties"]["action"]["type"] == "string"
        assert "enum" in params["properties"]["action"]
        assert "start" in params["properties"]["action"]["enum"]
        assert "stop" in params["properties"]["action"]["enum"]
        assert "status" in params["properties"]["action"]["enum"]

    def test_parameters_schema_has_port(self):
        """Test parameters schema defines optional port with default 7681."""
        params = terminal_tool.parameters
        assert "port" in params["properties"]
        assert params["properties"]["port"]["type"] == "integer"
        assert params["properties"]["port"]["default"] == 7681

    def test_parameters_schema_requires_action(self):
        """Test parameters schema lists action as required."""
        params = terminal_tool.parameters
        assert "action" in params["required"]

    async def test_execute_start_success(self, mock_adapter):
        """Test starting terminal returns success with port info."""
        configure_terminal(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "ws://localhost:7681", "port": 7681}',
                }
            ],
            "is_error": False,
        }

        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="start")

        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "7681" in result.output

    async def test_execute_start_with_custom_port(self, mock_adapter):
        """Test starting terminal with non-default port passes port in mcp args."""
        configure_terminal(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "ws://localhost:8681", "port": 8681}',
                }
            ],
            "is_error": False,
        }

        ctx = _make_ctx()
        await terminal_tool.execute(ctx, action="start", port=8681)

        call_args = mock_adapter.call_tool.call_args
        assert call_args[0][0] == "test-sandbox"
        assert call_args[0][1] == "start_terminal"
        assert call_args[0][2]["port"] == 8681

    async def test_execute_stop_success(self, mock_adapter):
        """Test stopping terminal returns success message."""
        configure_terminal(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {"type": "text", "text": '{"success": true, "message": "Terminal stopped"}'}
            ],
            "is_error": False,
        }

        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="stop")

        assert isinstance(result, ToolResult)
        assert not result.is_error
        call_args = mock_adapter.call_tool.call_args
        assert call_args[0][0] == "test-sandbox"
        assert call_args[0][1] == "stop_terminal"
        assert call_args[0][2] == {"_workspace_dir": "/workspace"}

    async def test_execute_status_running(self, mock_adapter):
        """Test getting status when terminal is running."""
        configure_terminal(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"running": true, "url": "ws://localhost:7681", "port": 7681}',
                }
            ],
            "is_error": False,
        }

        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="status")

        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "running" in result.output.lower()

    async def test_execute_error_handling(self, mock_adapter):
        """Test error handling when sandbox call returns is_error=True."""
        configure_terminal(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Terminal failed to start"}],
            "is_error": True,
        }

        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="start")

        assert isinstance(result, ToolResult)
        assert "error" in result.output.lower()

    async def test_execute_invalid_action_returns_error(self):
        """Test invalid action returns ToolResult with is_error=True."""
        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="invalid")

        assert isinstance(result, ToolResult)
        assert result.is_error
        assert "Unknown action" in result.output

    async def test_execute_no_adapter_returns_error(self):
        """Test that calling without adapter or orchestrator returns error."""
        configure_terminal()

        ctx = _make_ctx()
        result = await terminal_tool.execute(ctx, action="start")

        assert isinstance(result, ToolResult)
        assert result.is_error
        assert "no orchestrator" in result.output.lower() or "error" in result.output.lower()

class TestTerminalStatus:
    """Test suite for TerminalStatus data class."""

    def test_terminal_status_creation(self):
        """Test creating a TerminalStatus instance."""
        status = TerminalStatus(
            running=True,
            url="ws://localhost:7681",
            port=7681,
            session_id="abc123",
        )

        assert status.running is True
        assert status.url == "ws://localhost:7681"
        assert status.port == 7681
        assert status.session_id == "abc123"

    def test_terminal_status_default_values(self):
        """Test TerminalStatus with minimal required fields."""
        status = TerminalStatus(running=False)

        assert status.running is False
        assert status.url is None
