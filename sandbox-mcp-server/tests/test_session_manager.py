"""Tests for Session Manager.

TDD approach: Write tests first, expect failures, then implement.
The SessionManager unifies management of terminal and desktop sessions.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.session_manager import SessionManager, SessionStatus
from src.server.web_terminal import WebTerminalManager
from src.server.desktop_manager import DesktopManager


def create_mock_process(pid: int = 12345, returncode: int = None) -> MagicMock:
    """Create a mock process with proper attributes."""
    mock = MagicMock()
    mock.pid = pid
    mock.returncode = returncode
    mock.wait = AsyncMock()
    mock.terminate = MagicMock()
    mock.kill = MagicMock()
    return mock


class TestSessionManager:
    """Test suite for SessionManager."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.fixture
    def manager(self, workspace_dir):
        """Provide a SessionManager instance."""
        return SessionManager(workspace_dir=workspace_dir)

    def test_init_creates_manager(self, manager, workspace_dir):
        """Test that manager initializes with correct values."""
        assert manager.workspace_dir == workspace_dir
        assert manager.terminal_port == 7681
        assert manager.desktop_port == 6080
        assert manager.terminal_enabled is True
        assert manager.desktop_enabled is True
        assert isinstance(manager.terminal_manager, WebTerminalManager)
        assert isinstance(manager.desktop_manager, DesktopManager)

    def test_init_with_custom_config(self, workspace_dir):
        """Test that manager accepts custom configuration."""
        manager = SessionManager(
            workspace_dir=workspace_dir,
            terminal_port=8080,
            desktop_port=8081,
            terminal_enabled=False,
            desktop_enabled=False,
        )
        assert manager.terminal_port == 8080
        assert manager.desktop_port == 8081
        assert manager.terminal_enabled is False
        assert manager.desktop_enabled is False

    @pytest.mark.asyncio
    async def test_start_all_enabled_sessions(self, manager):
        """Test starting all enabled sessions."""
        mock_terminal = create_mock_process(pid=1001)
        mock_xvfb = create_mock_process(pid=2001)
        mock_lxde = create_mock_process(pid=2002)
        mock_xvnc = create_mock_process(pid=2003)
        mock_novnc = create_mock_process(pid=2004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Terminal needs 1 call, Desktop needs 4 calls
            mock_exec.side_effect = [
                mock_terminal,  # ttyd
                mock_xvfb, mock_lxde, mock_xvnc, mock_novnc,  # desktop
            ]

            await manager.start_all()

            assert manager.terminal_manager.is_running()
            assert manager.desktop_manager.is_running()

    @pytest.mark.asyncio
    async def test_start_with_terminal_disabled(self, workspace_dir):
        """Test starting with terminal disabled."""
        manager = SessionManager(
            workspace_dir=workspace_dir,
            terminal_enabled=False,
            desktop_enabled=True,
        )

        mock_xvfb = create_mock_process(pid=2001)
        mock_lxde = create_mock_process(pid=2002)
        mock_xvnc = create_mock_process(pid=2003)
        mock_novnc = create_mock_process(pid=2004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_xvfb, mock_lxde, mock_xvnc, mock_novnc]

            await manager.start_all()

            assert not manager.terminal_manager.is_running()
            assert manager.desktop_manager.is_running()

    @pytest.mark.asyncio
    async def test_start_with_desktop_disabled(self, workspace_dir):
        """Test starting with desktop disabled."""
        manager = SessionManager(
            workspace_dir=workspace_dir,
            terminal_enabled=True,
            desktop_enabled=False,
        )

        mock_terminal = create_mock_process(pid=1001)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_terminal]

            await manager.start_all()

            assert manager.terminal_manager.is_running()
            assert not manager.desktop_manager.is_running()

    @pytest.mark.asyncio
    async def test_stop_all_sessions(self, manager):
        """Test stopping all sessions."""
        mock_terminal = create_mock_process(pid=1001)
        mock_xvfb = create_mock_process(pid=2001)
        mock_lxde = create_mock_process(pid=2002)
        mock_xvnc = create_mock_process(pid=2003)
        mock_novnc = create_mock_process(pid=2004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [
                mock_terminal,
                mock_xvfb, mock_lxde, mock_xvnc, mock_novnc,
            ]

            await manager.start_all()
            assert manager.terminal_manager.is_running()
            assert manager.desktop_manager.is_running()

            await manager.stop_all()
            assert not manager.terminal_manager.is_running()
            assert not manager.desktop_manager.is_running()

    @pytest.mark.asyncio
    async def test_stop_all_when_none_running(self, manager):
        """Test that stopping when nothing is running is safe."""
        # Should not raise an error
        await manager.stop_all()
        assert not manager.terminal_manager.is_running()
        assert not manager.desktop_manager.is_running()

    @pytest.mark.asyncio
    async def test_restart_all_sessions(self, manager):
        """Test restarting all sessions."""
        mock_terminal = create_mock_process(pid=1001)
        mock_xvfb = create_mock_process(pid=2001)
        mock_lxde = create_mock_process(pid=2002)
        mock_xvnc = create_mock_process(pid=2003)
        mock_novnc = create_mock_process(pid=2004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [
                mock_terminal,
                mock_xvfb, mock_lxde, mock_xvnc, mock_novnc,
            ]

            await manager.start_all()

            # Set up for restart
            mock_terminal2 = create_mock_process(pid=1002)
            mock_xvfb2 = create_mock_process(pid=2005)
            mock_lxde2 = create_mock_process(pid=2006)
            mock_xvnc2 = create_mock_process(pid=2007)
            mock_novnc2 = create_mock_process(pid=2008)

            mock_exec.side_effect = [
                mock_terminal2,
                mock_xvfb2, mock_lxde2, mock_xvnc2, mock_novnc2,
            ]

            await manager.restart_all()

            # Verify processes are new
            assert manager.terminal_manager.process.pid == 1002
            assert manager.desktop_manager.xvfb_process.pid == 2005

    def test_get_status_when_not_running(self, manager):
        """Test status when sessions are not running."""
        status = manager.get_status()
        assert status.terminal_running is False
        assert status.desktop_running is False
        assert status.terminal_port == 7681
        assert status.desktop_port == 6080
        assert status.terminal_pid is None
        assert status.desktop_pid is None

    def test_get_status_when_running(self, manager):
        """Test status when sessions are running."""
        mock_terminal = create_mock_process(pid=1001)
        mock_xvfb = create_mock_process(pid=2001)

        manager.terminal_manager.process = mock_terminal
        manager.desktop_manager.xvfb_process = mock_xvfb

        status = manager.get_status()
        assert status.terminal_running is True
        assert status.desktop_running is True
        assert status.terminal_pid == 1001
        assert status.desktop_pid == 2001

    def test_get_terminal_info(self, manager):
        """Test getting terminal info."""
        info = manager.get_terminal_info()
        assert "enabled" in info
        assert "port" in info
        assert info["port"] == 7681
        assert "url" in info
        assert info["url"] == "ws://localhost:7681"

    def test_get_desktop_info(self, manager):
        """Test getting desktop info."""
        info = manager.get_desktop_info()
        assert "enabled" in info
        assert "port" in info
        assert info["port"] == 6080
        assert "url" in info
        assert info["url"] == "http://localhost:6080/vnc.html"
        assert "display" in info
        assert info["display"] == ":1"

    @pytest.mark.asyncio
    async def test_context_manager(self, manager):
        """Test that sessions are managed with context manager."""
        mock_terminal = create_mock_process(pid=1001)
        mock_xvfb = create_mock_process(pid=2001)
        mock_lxde = create_mock_process(pid=2002)
        mock_xvnc = create_mock_process(pid=2003)
        mock_novnc = create_mock_process(pid=2004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [
                mock_terminal,
                mock_xvfb, mock_lxde, mock_xvnc, mock_novnc,
            ]

            async with manager:
                assert manager.terminal_manager.is_running()
                assert manager.desktop_manager.is_running()

            assert not manager.terminal_manager.is_running()
            assert not manager.desktop_manager.is_running()


class TestSessionStatus:
    """Test suite for SessionStatus dataclass."""

    def test_session_status_creation(self):
        """Test creating a SessionStatus."""
        status = SessionStatus(
            terminal_running=True,
            desktop_running=True,
            terminal_port=7681,
            desktop_port=6080,
            terminal_pid=1001,
            desktop_pid=2001,
        )
        assert status.terminal_running is True
        assert status.desktop_running is True
        assert status.terminal_port == 7681
        assert status.desktop_port == 6080
        assert status.terminal_pid == 1001
        assert status.desktop_pid == 2001

    def test_session_status_default_values(self):
        """Test SessionStatus with default values."""
        status = SessionStatus(
            terminal_running=False,
            desktop_running=False,
            terminal_port=7681,
            desktop_port=6080,
        )
        assert status.terminal_running is False
        assert status.desktop_running is False
        assert status.terminal_pid is None
        assert status.desktop_pid is None
