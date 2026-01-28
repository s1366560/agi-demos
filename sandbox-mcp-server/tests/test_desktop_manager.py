"""Tests for Desktop Manager.

TDD approach: Write tests first, expect failures, then implement.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.server.desktop_manager import DesktopManager, DesktopStatus


def create_mock_process(pid: int = 12345, returncode: int = None) -> MagicMock:
    """Create a mock process with proper attributes."""
    mock = MagicMock()
    mock.pid = pid
    mock.returncode = returncode
    mock.wait = AsyncMock()
    mock.terminate = MagicMock()
    mock.kill = MagicMock()
    return mock


class TestDesktopManager:
    """Test suite for DesktopManager."""

    @pytest.fixture
    def workspace_dir(self, tmp_path):
        """Provide a temporary workspace directory."""
        return str(tmp_path / "workspace")

    @pytest.fixture
    def manager(self, workspace_dir):
        """Provide a DesktopManager instance."""
        return DesktopManager(workspace_dir=workspace_dir)

    def test_init_creates_manager(self, manager, workspace_dir):
        """Test that manager initializes with correct values."""
        assert manager.workspace_dir == workspace_dir
        assert manager.display == ":1"
        assert manager.resolution == "1280x720"
        assert manager.port == 6080
        assert manager.xvfb_process is None
        assert manager.xvnc_process is None
        assert manager.is_running() is False

    def test_init_with_custom_config(self, workspace_dir):
        """Test that manager accepts custom configuration."""
        manager = DesktopManager(
            workspace_dir=workspace_dir,
            display=":2",
            resolution="1920x1080",
            port=6081,
        )
        assert manager.display == ":2"
        assert manager.resolution == "1920x1080"
        assert manager.port == 6081

    @pytest.mark.asyncio
    async def test_start_desktop_success(self, manager):
        """Test successful desktop start."""
        mock_xvfb = create_mock_process(pid=1001)
        mock_lxde = create_mock_process(pid=1002)
        mock_xvnc = create_mock_process(pid=1003)
        mock_novnc = create_mock_process(pid=1004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            # Mock different calls to return different processes
            # Order: Xvfb, LXDE, x11vnc, noVNC
            mock_exec.side_effect = [mock_xvfb, mock_lxde, mock_xvnc, mock_novnc]

            await manager.start()

            # Verify processes were started
            assert mock_exec.call_count == 4
            assert manager.is_running() is True

    @pytest.mark.asyncio
    async def test_start_desktop_already_running(self, manager):
        """Test that starting when already running raises error."""
        mock_xvfb = create_mock_process(pid=1001)
        mock_lxde = create_mock_process(pid=1002)
        mock_xvnc = create_mock_process(pid=1003)
        mock_novnc = create_mock_process(pid=1004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_xvfb, mock_lxde, mock_xvnc, mock_novnc]
            await manager.start()

            # Try to start again
            with pytest.raises(RuntimeError, match="already running"):
                await manager.start()

    @pytest.mark.asyncio
    async def test_stop_desktop_success(self, manager):
        """Test successful desktop stop."""
        mock_xvfb = create_mock_process(pid=1001)
        mock_lxde = create_mock_process(pid=1002)
        mock_xvnc = create_mock_process(pid=1003)
        mock_novnc = create_mock_process(pid=1004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_xvfb, mock_lxde, mock_xvnc, mock_novnc]
            await manager.start()
            assert manager.is_running() is True

            await manager.stop()
            assert manager.is_running() is False

    @pytest.mark.asyncio
    async def test_stop_desktop_when_not_running(self, manager):
        """Test that stopping when not running is safe."""
        # Should not raise an error
        await manager.stop()
        assert manager.is_running() is False

    def test_get_status_when_not_running(self, manager):
        """Test status when desktop is not running."""
        status = manager.get_status()
        assert status.running is False
        assert status.display == ":1"
        assert status.resolution == "1280x720"
        assert status.port == 6080
        assert status.xvfb_pid is None
        assert status.xvnc_pid is None

    def test_get_status_when_running(self, manager):
        """Test status when desktop is running."""
        mock_xvfb = create_mock_process(pid=1001)
        mock_xvnc = create_mock_process(pid=1002)
        mock_novnc = create_mock_process(pid=1003)

        manager.xvfb_process = mock_xvfb
        manager.xvnc_process = mock_xvnc

        status = manager.get_status()
        assert status.running is True
        assert status.display == ":1"
        assert status.xvfb_pid == 1001
        assert status.xvnc_pid == 1002

    @pytest.mark.asyncio
    async def test_restart_stops_and_starts(self, manager):
        """Test restart stops and starts the desktop."""
        # First batch of processes
        mock_xvfb = create_mock_process(pid=1001)
        mock_xfce = create_mock_process(pid=1002)
        mock_xvnc = create_mock_process(pid=1003)
        mock_novnc = create_mock_process(pid=1004)
        mock_vncserver_kill = create_mock_process(pid=1005)  # vncserver -kill during stop

        # Second batch of processes (for restart)
        mock_xvfb2 = create_mock_process(pid=2001)
        mock_xfce2 = create_mock_process(pid=2002)
        mock_xvnc2 = create_mock_process(pid=2003)
        mock_novnc2 = create_mock_process(pid=2004)
        mock_vncserver_kill2 = create_mock_process(pid=2005)  # vncserver -kill during stop

        # Create an iterator that yields all processes in sequence
        process_iterator = iter([
            mock_xvfb, mock_xfce, mock_xvnc, mock_novnc,  # First start
            mock_vncserver_kill,  # vncserver -kill during stop
            mock_xvfb2, mock_xfce2, mock_xvnc2, mock_novnc2,  # Restart
        ])

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = lambda *args, **kwargs: next(process_iterator)
            await manager.start()
            await manager.restart()

            # Verify processes are new
            assert manager.xvfb_process.pid == 2001

    @pytest.mark.asyncio
    async def test_get_novnc_url(self, manager):
        """Test getting noVNC URL."""
        url = manager.get_novnc_url()
        assert url == "http://localhost:6080/vnc.html"

    @pytest.mark.asyncio
    async def test_get_novnc_url_with_custom_host(self, workspace_dir):
        """Test getting noVNC URL with custom host."""
        manager = DesktopManager(
            workspace_dir=workspace_dir,
            port=6081,
            host="0.0.0.0",
        )
        url = manager.get_novnc_url()
        assert url == "http://0.0.0.0:6081/vnc.html"

    @pytest.mark.asyncio
    async def test_cleanup_on_context_exit(self, manager):
        """Test that desktop is stopped when used as context manager."""
        mock_xvfb = create_mock_process(pid=1001)
        mock_lxde = create_mock_process(pid=1002)
        mock_xvnc = create_mock_process(pid=1003)
        mock_novnc = create_mock_process(pid=1004)

        with patch("asyncio.create_subprocess_exec") as mock_exec:
            mock_exec.side_effect = [mock_xvfb, mock_lxde, mock_xvnc, mock_novnc]

            async with manager:
                assert manager.is_running() is True

            assert manager.is_running() is False


class TestDesktopStatus:
    """Test suite for DesktopStatus dataclass."""

    def test_desktop_status_creation(self):
        """Test creating a DesktopStatus."""
        status = DesktopStatus(
            running=True,
            display=":1",
            resolution="1280x720",
            port=6080,
            xvfb_pid=1001,
            xvnc_pid=1002,
        )
        assert status.running is True
        assert status.display == ":1"
        assert status.resolution == "1280x720"
        assert status.port == 6080
        assert status.xvfb_pid == 1001
        assert status.xvnc_pid == 1002

    def test_desktop_status_default_values(self):
        """Test DesktopStatus with default values."""
        status = DesktopStatus(
            running=False,
            display=":1",
            resolution="1280x720",
            port=6080,
        )
        assert status.running is False
        assert status.xvfb_pid is None
        assert status.xvnc_pid is None
