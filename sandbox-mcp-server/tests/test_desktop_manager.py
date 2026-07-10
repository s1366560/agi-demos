"""Tests for DesktopManager."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.server.desktop_manager import DesktopManager, DesktopStatus


def create_mock_process(pid: int = 12345, returncode: int = 0) -> MagicMock:
    """Create a mock subprocess handle."""
    mock = MagicMock()
    mock.pid = pid
    mock.returncode = returncode
    mock.wait = AsyncMock()
    mock.communicate = AsyncMock(return_value=(b"", b""))
    mock.kill = MagicMock()
    return mock


class TestDesktopManager:
    """Test suite for DesktopManager."""

    @pytest.fixture(autouse=True)
    def runtime_auth(self, monkeypatch):
        monkeypatch.setenv("MCP_STATIC_TOKEN", "sandbox-runtime-secret")
        monkeypatch.setattr(
            "src.server.desktop_manager.write_kasm_password_file",
            lambda *_args: None,
        )

    @pytest.fixture
    def manager(self, tmp_path):
        """Create a DesktopManager rooted in a temporary workspace."""
        return DesktopManager(workspace_dir=str(tmp_path / "workspace"))

    def test_init_creates_manager(self, manager):
        """Test that manager initializes with KasmVNC defaults."""
        assert manager.display == ":1"
        assert manager.resolution == "1920x1080"
        assert manager.port == 6080
        assert manager.is_running() is False

    def test_get_web_url(self, manager):
        """Test getting the browser URL."""
        assert manager.get_web_url() == "https://localhost:6080"

    def test_get_status_when_not_running(self, manager):
        """Status should expose KasmVNC fields."""
        status = manager.get_status()
        assert status == DesktopStatus(
            running=False,
            display=":1",
            resolution="1920x1080",
            port=6080,
            kasmvnc_pid=None,
            audio_enabled=True,
            dynamic_resize=True,
            encoding="webp",
        )

    def test_is_running_ignores_unrelated_system_pid(self, manager):
        """A stray KasmVNC PID should not mark this manager as running."""
        with (
            patch.object(manager, "_is_port_listening", return_value=False),
            patch.object(manager, "_get_kasmvnc_pid", return_value=9999),
        ):
            assert manager.is_running() is False

    @pytest.mark.asyncio
    async def test_start_desktop_success(self, manager, tmp_path, monkeypatch):
        """Test successful desktop startup."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        mock_process = create_mock_process(pid=2001)

        with (
            patch.object(manager, "_get_kasmvnc_pid", return_value=None),
            patch.object(
                manager,
                "_is_port_listening",
                side_effect=[False, True, True, True],
            ),
            patch("asyncio.sleep", AsyncMock()),
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=mock_process),
            ) as mock_exec,
            patch("src.server.desktop_manager.write_kasm_password_file") as write_password,
        ):
            await manager.start()
            assert manager.is_running() is True

        assert manager._kasmvnc_started is True
        mock_exec.assert_awaited_once()
        args = mock_exec.await_args.args
        assert args[0] == "vncserver"
        assert args[1] == ":1"
        assert "-disableBasicAuth" not in args
        write_password.assert_called_once()
        assert write_password.call_args.args[1:] == ("sandbox", "sandbox-runtime-secret")

    @pytest.mark.asyncio
    async def test_start_desktop_fails_closed_without_runtime_auth(self, manager, monkeypatch):
        monkeypatch.delenv("SANDBOX_SERVICE_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("MCP_STATIC_TOKEN", raising=False)

        with (
            patch.object(manager, "_is_port_listening", return_value=False),
            patch("asyncio.create_subprocess_exec", AsyncMock()) as mock_exec,
            pytest.raises(RuntimeError, match="runtime authentication capability"),
        ):
            await manager.start()

        mock_exec.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_start_desktop_timeout_is_actionable(self, manager, tmp_path, monkeypatch):
        """Startup timeout should raise an actionable error."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))
        mock_process = create_mock_process(pid=2001)

        with (
            patch.object(manager, "_get_kasmvnc_pid", return_value=None),
            patch.object(manager, "_is_port_listening", return_value=False),
            patch("asyncio.sleep", AsyncMock()),
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(return_value=mock_process),
            ),
        ):
            with pytest.raises(RuntimeError, match="failed to start within timeout"):
                await manager.start()

    @pytest.mark.asyncio
    async def test_start_file_not_found_mentions_kasmvnc_install(
        self, manager, tmp_path, monkeypatch
    ):
        """Missing KasmVNC binary should surface an installation hint."""
        monkeypatch.setenv("HOME", str(tmp_path / "home"))

        with (
            patch.object(manager, "_get_kasmvnc_pid", return_value=None),
            patch.object(manager, "_is_port_listening", return_value=False),
            patch(
                "asyncio.create_subprocess_exec",
                AsyncMock(side_effect=FileNotFoundError()),
            ),
        ):
            with pytest.raises(RuntimeError, match="KasmVNC not installed"):
                await manager.start()

    @pytest.mark.asyncio
    async def test_stop_desktop_when_not_running(self, manager):
        """Stopping an idle desktop should be safe."""
        await manager.stop()
        assert manager.is_running() is False
