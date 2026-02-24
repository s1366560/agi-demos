"""Unit tests for DesktopTool.

Tests the desktop management tool for starting, stopping, and checking
the status of remote desktop sessions in sandbox environments.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.desktop_tool import (
    DesktopStatus,
    DesktopTool,
)


class TestDesktopTool:
    """Test suite for DesktopTool."""

    @pytest.fixture
    def mock_sandbox_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def desktop_tool(self, mock_sandbox_adapter):
        """Create a DesktopTool instance with mocked dependencies."""
        return DesktopTool(sandbox_adapter=mock_sandbox_adapter)

    def test_tool_initialization(self, desktop_tool):
        """Test tool is initialized with correct name and description."""
        assert desktop_tool.name == "desktop"
        assert "remote desktop" in desktop_tool.description.lower()
        assert (
            "noVNC" in desktop_tool.description
            or "LXDE" in desktop_tool.description
            or "KasmVNC" in desktop_tool.description
        )

    def test_get_parameters_schema(self, desktop_tool):
        """Test parameters schema is correctly defined."""
        schema = desktop_tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "action" in schema["properties"]
        assert schema["properties"]["action"]["type"] == "string"
        assert "enum" in schema["properties"]["action"]
        assert "start" in schema["properties"]["action"]["enum"]
        assert "stop" in schema["properties"]["action"]["enum"]
        assert "status" in schema["properties"]["action"]["enum"]

    def test_validate_args_valid_start(self, desktop_tool):
        """Test argument validation for valid start action."""
        assert desktop_tool.validate_args(action="start")

    def test_validate_args_valid_stop(self, desktop_tool):
        """Test argument validation for valid stop action."""
        assert desktop_tool.validate_args(action="stop")

    def test_validate_args_valid_status(self, desktop_tool):
        """Test argument validation for valid status action."""
        assert desktop_tool.validate_args(action="status")

    def test_validate_args_invalid_action(self, desktop_tool):
        """Test argument validation rejects invalid action."""
        assert not desktop_tool.validate_args(action="invalid")

    def test_validate_args_missing_action(self, desktop_tool):
        """Test argument validation rejects missing action."""
        assert not desktop_tool.validate_args()

    @pytest.mark.asyncio
    async def test_execute_start_success(self, desktop_tool, mock_sandbox_adapter):
        """Test starting desktop successfully."""
        # Mock successful response
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "http://localhost:6080/vnc.html", "port": 6080}',
                }
            ],
            "is_error": False,
        }

        result = await desktop_tool.execute(action="start", resolution="1280x720")

        assert "started successfully" in result.lower() or "successfully" in result.lower()
        assert "6080" in result
        mock_sandbox_adapter.call_tool.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_start_with_options(self, desktop_tool, mock_sandbox_adapter):
        """Test starting desktop with custom options."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "http://localhost:6080/vnc.html"}',
                }
            ],
            "is_error": False,
        }

        await desktop_tool.execute(
            action="start",
            resolution="1920x1080",
            display=":2",
            port=7080,
        )

        # Verify the tool was called with correct parameters
        call_args = mock_sandbox_adapter.call_tool.call_args
        assert call_args[0][1] == "start_desktop"
        assert "resolution" in call_args[0][2]

    @pytest.mark.asyncio
    async def test_execute_stop_success(self, desktop_tool, mock_sandbox_adapter):
        """Test stopping desktop successfully."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "message": "Desktop stopped successfully"}',
                }
            ],
            "is_error": False,
        }

        result = await desktop_tool.execute(action="stop")

        assert "stopped" in result.lower()
        mock_sandbox_adapter.call_tool.assert_called_once_with(
            "test_sandbox", "stop_desktop", {"_workspace_dir": "/workspace"}
        )

    @pytest.mark.asyncio
    async def test_execute_status_running(self, desktop_tool, mock_sandbox_adapter):
        """Test getting status when desktop is running."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"running": true, "url": "http://localhost:6080/vnc.html", "port": 6080, "display": ":1"}',
                }
            ],
            "is_error": False,
        }

        result = await desktop_tool.execute(action="status")

        assert "running" in result.lower()
        assert "6080" in result

    @pytest.mark.asyncio
    async def test_execute_status_stopped(self, desktop_tool, mock_sandbox_adapter):
        """Test getting status when desktop is stopped."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": '{"running": false, "url": null}'}],
            "is_error": False,
        }

        result = await desktop_tool.execute(action="status")

        assert "not running" in result.lower() or "stopped" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_error_handling(self, desktop_tool, mock_sandbox_adapter):
        """Test error handling when sandbox call fails."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Desktop not available"}],
            "is_error": True,
        }

        result = await desktop_tool.execute(action="start")

        assert "error" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_response_format(self, desktop_tool, mock_sandbox_adapter):
        """Test handling of invalid JSON response."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "invalid json"}],
            "is_error": False,
        }

        result = await desktop_tool.execute(action="status")

        # Should return a formatted error message
        assert "error" in result.lower() or "failed" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_invalid_action(self, desktop_tool):
        """Test execution with invalid action returns error."""
        result = await desktop_tool.execute(action="invalid")

        assert "invalid" in result.lower() or "unknown" in result.lower()


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
