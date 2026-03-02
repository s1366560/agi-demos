"""Unit tests for desktop_tool.

Tests the desktop management tool for starting, stopping, and checking
the status of remote desktop sessions in sandbox environments.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.context import ToolContext
from src.infrastructure.agent.tools.desktop_tool import (
    DesktopStatus,
    configure_desktop,
    desktop_tool,
)
from src.infrastructure.agent.tools.result import ToolResult


def _make_ctx() -> ToolContext:
    """Create a minimal ToolContext for testing."""
    return ToolContext(
        session_id="test-session",
        message_id="test-msg",
        call_id="test-call",
        agent_name="test-agent",
        conversation_id="test-conv",
    )


class TestDesktopTool:
    """Test suite for the @tool_define-based desktop_tool function."""

    @pytest.fixture(autouse=True)
    def _reset_desktop_state(self):
        """Reset module-level desktop state between tests."""
        configure_desktop()
        yield
        configure_desktop()

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock sandbox adapter with call_tool."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    # ------------------------------------------------------------------
    # Registration and metadata
    # ------------------------------------------------------------------

    def test_tool_registered_in_registry(self):
        """Test that desktop tool has correct name."""
        assert desktop_tool.name == "desktop"

    def test_tool_description_mentions_kasmvnc(self):
        """Test that description includes KasmVNC reference."""
        assert "KasmVNC" in desktop_tool.description

    def test_parameters_schema_structure(self):
        """Test parameters schema has correct structure and action enum."""
        schema = desktop_tool.parameters

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "action" in schema["properties"]
        assert schema["properties"]["action"]["type"] == "string"
        assert "enum" in schema["properties"]["action"]
        assert set(schema["properties"]["action"]["enum"]) == {"start", "stop", "status"}
        assert schema["required"] == ["action"]

    # ------------------------------------------------------------------
    # Start action
    # ------------------------------------------------------------------

    async def test_start_success_returns_url_and_port(self, mock_adapter):
        """Test starting desktop successfully returns URL and port info."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "http://localhost:6080/vnc.html", "port": 6080}',
                }
            ],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="start", resolution="1280x720")

        # Assert
        assert isinstance(result, ToolResult)
        assert not result.is_error
        assert "started successfully" in result.output.lower() or "successfully" in result.output.lower()
        assert "6080" in result.output
        mock_adapter.call_tool.assert_called_once()

    async def test_start_with_non_default_options_sends_custom_args(self, mock_adapter):
        """Test start with non-default options includes them in mcp_args."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "http://localhost:7080/vnc.html"}',
                }
            ],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        await desktop_tool.execute(
            ctx, action="start", resolution="2560x1440", display=":2", port=7080
        )

        # Assert
        call_args = mock_adapter.call_tool.call_args
        assert call_args[0][0] == "test-sandbox"
        assert call_args[0][1] == "start_desktop"
        args_dict = call_args[0][2]
        assert args_dict["resolution"] == "2560x1440"
        assert args_dict["display"] == ":2"
        assert args_dict["port"] == 7080

    async def test_start_with_defaults_omits_default_values(self, mock_adapter):
        """Test start with default values does not send them in mcp_args."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "http://localhost:6080/vnc.html"}',
                }
            ],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act  (all defaults: resolution=1920x1080, display=:1, port=6080)
        await desktop_tool.execute(ctx, action="start")

        # Assert - only _workspace_dir should be in args
        call_args = mock_adapter.call_tool.call_args
        args_dict = call_args[0][2]
        assert "resolution" not in args_dict
        assert "display" not in args_dict
        assert "port" not in args_dict
        assert args_dict["_workspace_dir"] == "/workspace"

    # ------------------------------------------------------------------
    # Stop action
    # ------------------------------------------------------------------

    async def test_stop_success_returns_stopped_message(self, mock_adapter):
        """Test stopping desktop successfully."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "message": "Desktop stopped successfully"}',
                }
            ],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="stop")

        # Assert
        assert isinstance(result, ToolResult)
        assert "stopped" in result.output.lower()
        mock_adapter.call_tool.assert_called_once_with(
            "test-sandbox", "stop_desktop", {"_workspace_dir": "/workspace"}
        )

    # ------------------------------------------------------------------
    # Status action
    # ------------------------------------------------------------------

    async def test_status_running_shows_url_and_port(self, mock_adapter):
        """Test getting status when desktop is running."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"running": true, "url": "http://localhost:6080/vnc.html", "port": 6080, "display": ":1"}',
                }
            ],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="status")

        # Assert
        assert isinstance(result, ToolResult)
        assert "running" in result.output.lower()
        assert "6080" in result.output

    async def test_status_stopped_shows_not_running(self, mock_adapter):
        """Test getting status when desktop is stopped."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '{"running": false, "url": null}'}],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="status")

        # Assert
        assert isinstance(result, ToolResult)
        assert "not running" in result.output.lower() or "stopped" in result.output.lower()

    # ------------------------------------------------------------------
    # Error handling
    # ------------------------------------------------------------------

    async def test_error_response_propagates_error_text(self, mock_adapter):
        """Test error handling when adapter returns is_error=True."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Desktop not available"}],
            "is_error": True,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="start")

        # Assert
        assert isinstance(result, ToolResult)
        assert "error" in result.output.lower()

    async def test_invalid_json_response_handled_gracefully(self, mock_adapter):
        """Test handling of invalid JSON response from adapter."""
        # Arrange
        configure_desktop(sandbox_port=mock_adapter, sandbox_id="test-sandbox")
        mock_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "invalid json"}],
            "is_error": False,
        }
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="status")

        # Assert
        assert isinstance(result, ToolResult)
        # "invalid" is an error word, so it gets prefixed with "Error:"
        assert "error" in result.output.lower()

    # ------------------------------------------------------------------
    # Invalid action
    # ------------------------------------------------------------------

    async def test_invalid_action_returns_error(self):
        """Test execution with unknown action returns ToolResult with is_error."""
        # Arrange
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="invalid")

        # Assert
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "Unknown action" in result.output

    # ------------------------------------------------------------------
    # No adapter configured
    # ------------------------------------------------------------------

    async def test_no_adapter_configured_returns_error(self):
        """Test that executing without adapter/orchestrator returns error."""
        # Arrange - configure_desktop() already called by autouse fixture (no deps)
        ctx = _make_ctx()

        # Act
        result = await desktop_tool.execute(ctx, action="start")

        # Assert
        assert isinstance(result, ToolResult)
        assert result.is_error is True
        assert "No orchestrator or sandbox adapter" in result.output


class TestDesktopStatus:
    """Test suite for DesktopStatus data class."""

    def test_desktop_status_creation(self):
        """Test creating a DesktopStatus instance."""
        status = DesktopStatus(
            running=True,
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1280x720",
            port=6080,
        )

        assert status.running is True
        assert status.url == "http://localhost:6080/vnc.html"
        assert status.display == ":1"
        assert status.resolution == "1280x720"
        assert status.port == 6080

    def test_desktop_status_default_values(self):
        """Test DesktopStatus with minimal required fields."""
        status = DesktopStatus(running=False)

        assert status.running is False
        assert status.url is None
