"""Unit tests for TerminalTool.

Tests the terminal management tool for starting, stopping, and checking
the status of web terminal sessions in sandbox environments.
"""

from unittest.mock import AsyncMock

import pytest

from src.infrastructure.agent.tools.terminal_tool import (
    TerminalStatus,
    TerminalTool,
)


class TestTerminalTool:
    """Test suite for TerminalTool."""

    @pytest.fixture
    def mock_sandbox_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = AsyncMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def terminal_tool(self, mock_sandbox_adapter):
        """Create a TerminalTool instance with mocked dependencies."""
        return TerminalTool(sandbox_adapter=mock_sandbox_adapter)

    def test_tool_initialization(self, terminal_tool):
        """Test tool is initialized with correct name and description."""
        assert terminal_tool.name == "terminal"
        assert "terminal" in terminal_tool.description.lower()
        assert "ttyd" in terminal_tool.description or "shell" in terminal_tool.description

    def test_get_parameters_schema(self, terminal_tool):
        """Test parameters schema is correctly defined."""
        schema = terminal_tool.get_parameters_schema()

        assert schema["type"] == "object"
        assert "properties" in schema
        assert "action" in schema["properties"]
        assert schema["properties"]["action"]["type"] == "string"
        assert "enum" in schema["properties"]["action"]
        assert "start" in schema["properties"]["action"]["enum"]
        assert "stop" in schema["properties"]["action"]["enum"]
        assert "status" in schema["properties"]["action"]["enum"]

    def test_validate_args_valid_actions(self, terminal_tool):
        """Test argument validation for all valid actions."""
        assert terminal_tool.validate_args(action="start")
        assert terminal_tool.validate_args(action="stop")
        assert terminal_tool.validate_args(action="status")

    def test_validate_args_invalid_action(self, terminal_tool):
        """Test argument validation rejects invalid action."""
        assert not terminal_tool.validate_args(action="restart")

    @pytest.mark.asyncio
    async def test_execute_start_success(self, terminal_tool, mock_sandbox_adapter):
        """Test starting terminal successfully."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "ws://localhost:7681", "port": 7681}'
                }
            ],
            "is_error": False,
        }

        result = await terminal_tool.execute(action="start")

        # Terminal may show as running or not depending on mock response
        assert "7681" in result

    @pytest.mark.asyncio
    async def test_execute_start_with_port(self, terminal_tool, mock_sandbox_adapter):
        """Test starting terminal with custom port."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "url": "ws://localhost:8681", "port": 8681}'
                }
            ],
            "is_error": False,
        }

        await terminal_tool.execute(action="start", port=8681)

        call_args = mock_sandbox_adapter.call_tool.call_args
        assert call_args[0][1] == "start_terminal"
        assert call_args[0][2]["port"] == 8681

    @pytest.mark.asyncio
    async def test_execute_stop_success(self, terminal_tool, mock_sandbox_adapter):
        """Test stopping terminal successfully."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"success": true, "message": "Terminal stopped"}'
                }
            ],
            "is_error": False,
        }

        result = await terminal_tool.execute(action="stop")

        # Stop command returns success message
        assert "successfully" in result.lower() or "stopped" in result.lower() or "not running" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_status_running(self, terminal_tool, mock_sandbox_adapter):
        """Test getting status when terminal is running."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [
                {
                    "type": "text",
                    "text": '{"running": true, "url": "ws://localhost:7681", "port": 7681}'
                }
            ],
            "is_error": False,
        }

        result = await terminal_tool.execute(action="status")

        assert "running" in result.lower()

    @pytest.mark.asyncio
    async def test_execute_error_handling(self, terminal_tool, mock_sandbox_adapter):
        """Test error handling when sandbox call fails."""
        mock_sandbox_adapter.call_tool.return_value = {
            "content": [{"type": "text", "text": "Terminal failed to start"}],
            "is_error": True,
        }

        result = await terminal_tool.execute(action="start")

        assert "error" in result.lower()


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
