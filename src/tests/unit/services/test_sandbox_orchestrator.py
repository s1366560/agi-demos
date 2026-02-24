"""Unit tests for SandboxOrchestrator.

TDD Phase 1: Write failing tests first (RED).
Tests the unified sandbox service orchestration layer.
"""

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.application.services.sandbox_orchestrator import (
    CommandResult,
    DesktopConfig,
    DesktopStatus,
    SandboxOrchestrator,
    TerminalConfig,
    TerminalStatus,
)


class TestDesktopConfig:
    """Test DesktopConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = DesktopConfig()

        assert config.resolution == "1920x1080"
        assert config.display == ":1"
        assert config.port == 6080

    def test_custom_config(self):
        """Test custom configuration values."""
        config = DesktopConfig(
            resolution="1920x1080",
            display=":2",
            port=8080,
        )

        assert config.resolution == "1920x1080"
        assert config.display == ":2"
        assert config.port == 8080


class TestTerminalConfig:
    """Test TerminalConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TerminalConfig()

        assert config.port == 7681
        assert config.shell == "/bin/bash"

    def test_custom_config(self):
        """Test custom configuration values."""
        config = TerminalConfig(
            port=8081,
            shell="/bin/zsh",
        )

        assert config.port == 8081
        assert config.shell == "/bin/zsh"


class TestDesktopStatus:
    """Test DesktopStatus dataclass."""

    def test_running_status(self):
        """Test desktop status when running."""
        status = DesktopStatus(
            running=True,
            url="http://localhost:6080/vnc.html",
            display=":1",
            resolution="1920x1080",
            port=6080,
            pid=12345,
        )

        assert status.running is True
        assert status.url == "http://localhost:6080/vnc.html"
        assert status.display == ":1"
        assert status.resolution == "1920x1080"
        assert status.port == 6080
        assert status.pid == 12345

    def test_not_running_status(self):
        """Test desktop status when not running."""
        status = DesktopStatus(
            running=False,
            url=None,
            display="",
            resolution="",
            port=0,
            pid=None,
        )

        assert status.running is False
        assert status.url is None
        assert status.display == ""
        assert status.resolution == ""
        assert status.port == 0
        assert status.pid is None


class TestTerminalStatus:
    """Test TerminalStatus dataclass."""

    def test_running_status(self):
        """Test terminal status when running."""
        status = TerminalStatus(
            running=True,
            url="ws://localhost:7681",
            port=7681,
            pid=54321,
            session_id="sess-abc",
        )

        assert status.running is True
        assert status.url == "ws://localhost:7681"
        assert status.port == 7681
        assert status.pid == 54321
        assert status.session_id == "sess-abc"

    def test_not_running_status(self):
        """Test terminal status when not running."""
        status = TerminalStatus(
            running=False,
            url=None,
            port=0,
            pid=None,
            session_id=None,
        )

        assert status.running is False
        assert status.url is None
        assert status.port == 0
        assert status.pid is None
        assert status.session_id is None


class TestCommandResult:
    """Test CommandResult dataclass."""

    def test_successful_command(self):
        """Test command result for successful execution."""
        result = CommandResult(
            exit_code=0,
            stdout="file1.txt\nfile2.txt",
            stderr="",
            execution_time_ms=150,
        )

        assert result.exit_code == 0
        assert result.stdout == "file1.txt\nfile2.txt"
        assert result.stderr == ""
        assert result.execution_time_ms == 150

    def test_failed_command(self):
        """Test command result for failed execution."""
        result = CommandResult(
            exit_code=1,
            stdout="",
            stderr="Command not found: xyz",
            execution_time_ms=50,
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == "Command not found: xyz"
        assert result.execution_time_ms == 50


class TestSandboxOrchestrator:
    """Test SandboxOrchestrator."""

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock sandbox adapter."""
        adapter = MagicMock()
        adapter.call_tool = AsyncMock()
        return adapter

    @pytest.fixture
    def mock_event_publisher(self):
        """Create a mock event publisher."""
        publisher = AsyncMock()
        publisher.publish = AsyncMock()
        return publisher

    @pytest.fixture
    def orchestrator(self, mock_adapter, mock_event_publisher):
        """Create orchestrator with mocked dependencies."""
        return SandboxOrchestrator(
            sandbox_adapter=mock_adapter,
            event_publisher=mock_event_publisher,
            default_timeout=30,
        )

    # ========================================================================
    # Desktop Management Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_start_desktop_success(self, orchestrator, mock_adapter, mock_event_publisher):
        """Test successful desktop start."""
        # Setup mock response
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "success": True,
                            "url": "http://localhost:6080/vnc.html",
                            "display": ":1",
                            "resolution": "1920x1080",  # Should match requested resolution
                            "port": 6080,
                            "kasmvnc_pid": 12345,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        # Execute
        config = DesktopConfig(resolution="1920x1080")
        status = await orchestrator.start_desktop("sb-123", config)

        # Verify result
        assert status.running is True
        assert status.url == "http://localhost:6080/vnc.html"
        assert status.resolution == "1920x1080"
        assert status.port == 6080
        assert status.pid == 12345

        # Verify adapter was called correctly
        mock_adapter.call_tool.assert_called_once_with(
            "sb-123",
            "start_desktop",
            {
                "resolution": "1920x1080",
                "display": ":1",
                "port": 6080,
                "_workspace_dir": "/workspace",
            },
            timeout=30,
        )

    @pytest.mark.asyncio
    async def test_start_desktop_with_default_config(self, orchestrator, mock_adapter):
        """Test desktop start with default configuration."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "success": True,
                            "url": "http://localhost:6080/vnc.html",
                            "display": ":1",
                            "resolution": "1280x720",
                            "port": 6080,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = await orchestrator.start_desktop("sb-123")

        assert status.resolution == "1280x720"
        assert status.display == ":1"

    @pytest.mark.asyncio
    async def test_start_desktop_already_running(self, orchestrator, mock_adapter):
        """Test desktop start when already running."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "success": True,
                            "message": "Desktop already running",
                            "url": "http://localhost:6080/vnc.html",
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = await orchestrator.start_desktop("sb-123")

        # Parser should handle the alternative format
        assert status.running is True  # or based on actual parsing

    @pytest.mark.asyncio
    async def test_start_desktop_error(self, orchestrator, mock_adapter):
        """Test desktop start with error."""
        mock_adapter.call_tool.side_effect = Exception("Connection failed")

        with pytest.raises(Exception):
            await orchestrator.start_desktop("sb-123")

    @pytest.mark.asyncio
    async def test_stop_desktop_success(self, orchestrator, mock_adapter, mock_event_publisher):
        """Test successful desktop stop."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": json.dumps({"success": True})}],
            "is_error": False,
        }

        result = await orchestrator.stop_desktop("sb-123")

        assert result is True
        mock_adapter.call_tool.assert_called_once_with(
            "sb-123",
            "stop_desktop",
            {"_workspace_dir": "/workspace"},
            timeout=30,
        )
        # Event publishing is now handled by the API layer

    @pytest.mark.asyncio
    async def test_stop_desktop_error(self, orchestrator, mock_adapter):
        """Test desktop stop with error."""
        mock_adapter.call_tool.side_effect = Exception("Stop failed")

        result = await orchestrator.stop_desktop("sb-123")

        assert result is False  # Should handle error gracefully

    @pytest.mark.asyncio
    async def test_get_desktop_status_running(self, orchestrator, mock_adapter):
        """Test getting desktop status when running."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "running": True,
                            "url": "http://localhost:6080/vnc.html",
                            "display": ":1",
                            "resolution": "1280x720",
                            "port": 6080,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = await orchestrator.get_desktop_status("sb-123")

        assert status.running is True
        assert status.url == "http://localhost:6080/vnc.html"

    @pytest.mark.asyncio
    async def test_get_desktop_status_not_running(self, orchestrator, mock_adapter):
        """Test getting desktop status when not running."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "running": False,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = await orchestrator.get_desktop_status("sb-123")

        assert status.running is False
        assert status.url is None

    # ========================================================================
    # Terminal Management Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_start_terminal_success(self, orchestrator, mock_adapter, mock_event_publisher):
        """Test successful terminal start."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "success": True,
                            "url": "ws://localhost:7681",
                            "port": 7681,
                            "pid": 54321,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        config = TerminalConfig(port=8081)
        status = await orchestrator.start_terminal("sb-123", config)

        assert status.running is True
        assert status.url == "ws://localhost:7681"
        assert status.port == 7681
        assert status.pid == 54321

        mock_adapter.call_tool.assert_called_once_with(
            "sb-123",
            "start_terminal",
            {
                "port": 8081,
                "_workspace_dir": "/workspace",
            },
            timeout=30,
        )
        # Event publishing is now handled by the API layer

    @pytest.mark.asyncio
    async def test_stop_terminal_success(self, orchestrator, mock_adapter, mock_event_publisher):
        """Test successful terminal stop."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": json.dumps({"success": True})}],
            "is_error": False,
        }

        result = await orchestrator.stop_terminal("sb-123")

        assert result is True
        mock_adapter.call_tool.assert_called_once_with(
            "sb-123",
            "stop_terminal",
            {"_workspace_dir": "/workspace"},
            timeout=30,
        )
        # Event publishing is now handled by the API layer

    @pytest.mark.asyncio
    async def test_get_terminal_status_running(self, orchestrator, mock_adapter):
        """Test getting terminal status when running."""
        mock_adapter.call_tool.return_value = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "running": True,
                            "url": "ws://localhost:7681",
                            "port": 7681,
                            "pid": 54321,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = await orchestrator.get_terminal_status("sb-123")

        assert status.running is True
        assert status.url == "ws://localhost:7681"

    # ========================================================================
    # Command Execution Tests
    # ========================================================================

    @pytest.mark.asyncio
    async def test_execute_command_success(self, orchestrator, mock_adapter):
        """Test successful command execution."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "file1.txt\nfile2.txt\n"}],
            "is_error": False,
        }

        result = await orchestrator.execute_command(
            "sb-123",
            "ls -la",
            working_dir="/workspace",
        )

        assert result.exit_code == 0
        assert "file1.txt" in result.stdout
        assert result.stderr == ""
        # execution_time_ms may be 0 in tests due to fast mock execution
        assert result.execution_time_ms >= 0

        mock_adapter.call_tool.assert_called_once_with(
            "sb-123",
            "bash",
            {
                "command": "ls -la",
                "working_dir": "/workspace",
                "timeout": 60,
                "_workspace_dir": "/workspace",
            },
            timeout=65,
        )

    @pytest.mark.asyncio
    async def test_execute_command_with_error(self, orchestrator, mock_adapter):
        """Test command execution that produces error output."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "Error: Command not found"}],
            "is_error": True,
        }

        result = await orchestrator.execute_command(
            "sb-123",
            "xyz command",
        )

        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Error: Command not found" in result.stderr

    @pytest.mark.asyncio
    async def test_execute_command_with_custom_timeout(self, orchestrator, mock_adapter):
        """Test command execution with custom timeout."""
        mock_adapter.call_tool.return_value = {
            "content": [{"text": "done"}],
            "is_error": False,
        }

        result = await orchestrator.execute_command(
            "sb-123",
            "sleep 1",
            timeout=120,
        )

        assert result.exit_code == 0
        mock_adapter.call_tool.assert_called_once()
        call_args = mock_adapter.call_tool.call_args
        # Verify timeout parameter in kwargs
        assert call_args[1]["timeout"] == 125  # timeout + 5

    # ========================================================================
    # Result Parsing Tests
    # ========================================================================

    def test_parse_desktop_result_running(self, orchestrator):
        """Test parsing desktop result when running."""
        result = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "running": True,
                            "url": "http://localhost:6080/vnc.html",
                            "display": ":1",
                            "resolution": "1920x1080",
                            "port": 6080,
                            "kasmvnc_pid": 12345,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = orchestrator._parse_desktop_result(result)

        assert status.running is True
        assert status.url == "http://localhost:6080/vnc.html"
        assert status.display == ":1"
        assert status.resolution == "1920x1080"
        assert status.port == 6080
        assert status.pid == 12345

    def test_parse_desktop_result_not_running(self, orchestrator):
        """Test parsing desktop result when not running."""
        result = {
            "content": [{"text": json.dumps({"running": False})}],
            "is_error": False,
        }

        status = orchestrator._parse_desktop_result(result)

        assert status.running is False
        assert status.url is None

    def test_parse_desktop_result_empty_content(self, orchestrator):
        """Test parsing desktop result with empty content."""
        result = {"content": [], "is_error": False}

        status = orchestrator._parse_desktop_result(result)

        assert status.running is False
        assert status.url is None

    def test_parse_desktop_result_invalid_json(self, orchestrator):
        """Test parsing desktop result with invalid JSON."""
        result = {
            "content": [{"text": "invalid json"}],
            "is_error": False,
        }

        status = orchestrator._parse_desktop_result(result)

        assert status.running is False
        assert status.url is None

    def test_parse_terminal_result_running(self, orchestrator):
        """Test parsing terminal result when running."""
        result = {
            "content": [
                {
                    "text": json.dumps(
                        {
                            "running": True,
                            "url": "ws://localhost:7681",
                            "port": 7681,
                            "pid": 54321,
                        }
                    )
                }
            ],
            "is_error": False,
        }

        status = orchestrator._parse_terminal_result(result)

        assert status.running is True
        assert status.url == "ws://localhost:7681"
        assert status.port == 7681
        assert status.pid == 54321

    def test_parse_terminal_result_not_running(self, orchestrator):
        """Test parsing terminal result when not running."""
        result = {
            "content": [{"text": json.dumps({"running": False})}],
            "is_error": False,
        }

        status = orchestrator._parse_terminal_result(result)

        assert status.running is False
        assert status.url is None

    def test_parse_terminal_result_empty_content(self, orchestrator):
        """Test parsing terminal result with empty content."""
        result = {"content": [], "is_error": False}

        status = orchestrator._parse_terminal_result(result)

        assert status.running is False
        assert status.url is None
