"""Tests for Web Terminal Manager.

TDD approach: Write tests first, expect failures, then implement.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.web_terminal import WebTerminalManager, TerminalStatus


def create_mock_process(pid: int = 12345, returncode: int = None) -> MagicMock:
    """Create a mock process with proper attributes."""
    mock = MagicMock()
    mock.pid = pid
    mock.returncode = returncode
    mock.wait = AsyncMock()
    mock.terminate = MagicMock()
    mock.kill = MagicMock()
    return mock


class TestWebTerminalManager:
    """Test suite for WebTerminalManager."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.fixture
    def manager(self, workspace_dir):
        """Provide a WebTerminalManager instance."""
        return WebTerminalManager(workspace_dir=workspace_dir)

    def test_init_creates_manager(self, manager, workspace_dir):
        """Test that manager initializes with correct values."""
        assert manager.workspace_dir == workspace_dir
        assert manager.port == 7681
        assert manager.process is None
        assert manager.is_running() is False

    def test_init_with_custom_port(self, workspace_dir):
        """Test that manager accepts custom port."""
        manager = WebTerminalManager(workspace_dir=workspace_dir, port=8080)
        assert manager.port == 8080

    @pytest.mark.asyncio
    async def test_start_ttyd_success(self, manager):
        """Test successful ttyd start."""
        mock_process = create_mock_process()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process) as mock_exec:
            await manager.start()

            # Verify ttyd was called with correct arguments
            mock_exec.assert_called_once()
            args = mock_exec.call_args[0]
            assert args[0] == "ttyd"
            assert "-p" in args
            assert str(manager.port) in args

            assert manager.is_running() is True

    @pytest.mark.asyncio
    async def test_start_ttyd_already_running(self, manager):
        """Test that starting when already running raises error."""
        mock_process = create_mock_process()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await manager.start()

            # Try to start again
            with pytest.raises(RuntimeError, match="already running"):
                await manager.start()

    @pytest.mark.asyncio
    async def test_stop_ttyd_success(self, manager):
        """Test successful ttyd stop."""
        mock_process = create_mock_process()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await manager.start()
            assert manager.is_running() is True

            await manager.stop()
            assert manager.is_running() is False
            mock_process.terminate.assert_called_once()

    @pytest.mark.asyncio
    async def test_stop_ttyd_when_not_running(self, manager):
        """Test that stopping when not running is safe."""
        # Should not raise an error
        await manager.stop()
        assert manager.is_running() is False

    @pytest.mark.asyncio
    async def test_stop_force_kill_after_timeout(self, manager):
        """Test that force kill is used if graceful shutdown fails."""
        mock_process = create_mock_process()
        mock_process.wait.side_effect = asyncio.TimeoutError()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await manager.start()

            with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError()):
                await manager.stop(force_timeout=0.1)

            mock_process.terminate.assert_called_once()
            mock_process.kill.assert_called_once()

    def test_get_status_when_not_running(self, manager):
        """Test status when terminal is not running."""
        status = manager.get_status()
        assert status.running is False
        assert status.port == 7681
        assert status.pid is None

    def test_get_status_when_running(self, manager):
        """Test status when terminal is running."""
        mock_process = create_mock_process()
        manager.process = mock_process

        status = manager.get_status()
        assert status.running is True
        assert status.port == 7681
        assert status.pid == 12345

    @pytest.mark.asyncio
    async def test_restart_stops_and_starts(self, manager):
        """Test restart stops and starts the terminal."""
        mock_process = create_mock_process()
        mock_process2 = create_mock_process(pid=54321)

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            await manager.start()

            # Set up for second start
            with patch("asyncio.create_subprocess_exec", return_value=mock_process2) as mock_exec:
                await manager.restart()

                # Verify stop was called
                mock_process.terminate.assert_called_once()
                # Verify start was called
                assert mock_exec.call_count >= 1

    @pytest.mark.asyncio
    async def test_get_websocket_url(self, manager):
        """Test getting WebSocket URL."""
        url = manager.get_websocket_url()
        assert url == "ws://localhost:7681"

    @pytest.mark.asyncio
    async def test_get_websocket_url_with_custom_host(self, workspace_dir):
        """Test getting WebSocket URL with custom host."""
        manager = WebTerminalManager(workspace_dir=workspace_dir, port=7681, host="0.0.0.0")
        url = manager.get_websocket_url()
        assert url == "ws://0.0.0.0:7681"

    @pytest.mark.asyncio
    async def test_cleanup_on_context_exit(self, manager):
        """Test that terminal is stopped when used as context manager."""
        mock_process = create_mock_process()

        with patch("asyncio.create_subprocess_exec", return_value=mock_process):
            async with manager:
                assert manager.is_running() is True

            assert manager.is_running() is False
            mock_process.terminate.assert_called_once()


class TestTerminalStatus:
    """Test suite for TerminalStatus dataclass."""

    def test_terminal_status_creation(self):
        """Test creating a TerminalStatus."""
        status = TerminalStatus(running=True, port=7681, pid=12345)
        assert status.running is True
        assert status.port == 7681
        assert status.pid == 12345

    def test_terminal_status_default_values(self):
        """Test TerminalStatus with default values."""
        status = TerminalStatus(running=False, port=7681)
        assert status.running is False
        assert status.port == 7681
        assert status.pid is None
