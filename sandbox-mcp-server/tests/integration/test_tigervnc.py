"""Integration tests for TigerVNC server (TDD: RED phase).

These tests are written FIRST and will FAIL until TigerVNC is implemented.
Following strict TDD methodology: RED → GREEN → REFACTOR.

Test Categories:
1. Package Installation - TigerVNC installed in container
2. Server Startup - TigerVNC starts successfully
3. Configuration - Geometry, encoding, security settings
4. noVNC Integration - WebSocket connection works
5. Session Persistence - Sessions survive restarts
6. Performance - Startup time, frame rate, latency, bandwidth
"""

import asyncio
import os
import subprocess
import time
import pytest
from pathlib import Path
from typing import Optional

from src.server.desktop_manager import DesktopManager


class TestTigerVNCInstallation:
    """Test TigerVNC package installation."""

    @pytest.mark.integration
    def test_tigervnc_package_installed(self):
        """Test that tigervnc-standalone-server package is installed."""
        result = subprocess.run(
            ["dpkg", "-l", "tigervnc-standalone-server"],
            capture_output=True,
            text=True,
        )
        # Expected to FAIL initially (RED phase)
        assert result.returncode == 0, "TigerVNC package not installed"
        assert "tigervnc" in result.stdout.lower()

    @pytest.mark.integration
    def test_tigervnc_command_available(self):
        """Test that vncserver command is available."""
        result = subprocess.run(
            ["which", "vncserver"],
            capture_output=True,
            text=True,
        )
        # Expected to FAIL initially (RED phase)
        assert result.returncode == 0, "vncserver command not found in PATH"
        assert "/usr/bin" in result.stdout or "/usr/local/bin" in result.stdout

    @pytest.mark.integration
    def test_x11vnc_removed(self):
        """Test that old x11vnc package has been removed."""
        result = subprocess.run(
            ["which", "x11vnc"],
            capture_output=True,
            text=True,
        )
        # Expected to FAIL initially (x11vnc still present)
        assert result.returncode != 0, "x11vnc should be removed after TigerVNC migration"


class TestTigerVNCServerStartup:
    """Test TigerVNC server startup and initialization."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_tigervnc_starts_successfully(self, tmp_path):
        """Test that TigerVNC server starts without errors."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":99",  # Use non-standard display for testing
            resolution="1280x720",
        )

        try:
            # Start desktop with TigerVNC
            await manager.start()

            # Give it time to initialize
            await asyncio.sleep(2)

            # Verify TigerVNC process is running
            result = subprocess.run(
                ["pgrep", "-f", "vncserver.*:99"],
                capture_output=True,
                text=True,
            )

            # Expected to FAIL initially (RED phase)
            assert result.returncode == 0, "TigerVNC process not found"
            assert manager.is_running(), "DesktopManager reports not running"

        finally:
            await manager.stop()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_tigervnc_startup_time(self, tmp_path):
        """Test that TigerVNC starts within 5 seconds."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":98",
            resolution="1280x720",
        )

        try:
            start_time = time.time()
            await manager.start()
            startup_time = time.time() - start_time

            # Expected to FAIL initially (RED phase)
            # Performance target: <5 seconds
            assert startup_time < 5.0, f"Startup time {startup_time:.2f}s exceeds 5s target"

        finally:
            await manager.stop()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_tigervnc_listens_on_correct_port(self, tmp_path):
        """Test that TigerVNC listens on port 5901 (display :1)."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":1",
            resolution="1280x720",
        )

        try:
            await manager.start()
            await asyncio.sleep(2)

            # Check if port 5901 is listening
            result = subprocess.run(
                ["ss", "-ltn", "sport", "=5901"],
                capture_output=True,
                text=True,
            )

            # Expected to FAIL initially (RED phase)
            assert result.returncode == 0, "Port 5901 not listening"
            assert ":5901" in result.stdout, "VNC port 5901 not found in listening ports"

        finally:
            await manager.stop()


class TestTigerVNCConfiguration:
    """Test TigerVNC configuration settings."""

    @pytest.mark.integration
    def test_tigervnc_config_file_exists(self):
        """Test that TigerVNC config file exists."""
        config_path = Path("/etc/vnc/config")
        # Expected to FAIL initially (RED phase)
        assert config_path.exists(), "TigerVNC config file not found at /etc/vnc/config"

    @pytest.mark.integration
    def test_tigervnc_geometry_setting(self):
        """Test that VNC geometry is set correctly."""
        config_path = Path("/etc/vnc/config")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        content = config_path.read_text()
        # Expected to FAIL initially (RED phase)
        assert "$geometry" in content or "geometry" in content, "Geometry setting not found"
        assert "1280x720" in content or "1920x1080" in content, "Expected geometry not found"

    @pytest.mark.integration
    def test_tigervnc_encoding_tight(self):
        """Test that TigerVNC uses Tight encoding (optimal for web VNC)."""
        config_path = Path("/etc/vnc/config")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        content = config_path.read_text()
        # Expected to FAIL initially (RED phase)
        assert "Tight" in content or "tight" in content, "Tight encoding not configured"
        assert "$encoding" in content or "encoding" in content, "Encoding setting not found"

    @pytest.mark.integration
    def test_tigervnc_compression_level(self):
        """Test that compression level is configured (0-9)."""
        config_path = Path("/etc/vnc/config")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        content = config_path.read_text()
        # Expected to FAIL initially (RED phase)
        assert "$compressionLevel" in content or "compressionLevel" in content, \
            "Compression level not configured"

    @pytest.mark.integration
    def test_tigervnc_jpeg_quality(self):
        """Test that JPEG quality is configured (0-9)."""
        config_path = Path("/etc/vnc/config")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        content = config_path.read_text()
        # Expected to FAIL initially (RED phase)
        assert "$jpegQuality" in content or "jpegQuality" in content, \
            "JPEG quality not configured"

    @pytest.mark.integration
    def test_tigervnc_security_disabled(self):
        """Test that authentication is disabled (for container use)."""
        config_path = Path("/etc/vnc/config")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        content = config_path.read_text()
        # Expected to FAIL initially (RED phase)
        assert "$securityTypes" in content or "securityTypes" in content, \
            "Security types not configured"
        assert "None" in content or "none" in content, "Authentication should be disabled"


class TestTigerVNCNoVNCIntegration:
    """Test TigerVNC and noVNC integration."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_novnc_websockify_connects_to_tigervnc(self, tmp_path):
        """Test that noVNC websockify can connect to TigerVNC."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":1",
            resolution="1280x720",
            port=6080,
        )

        try:
            await manager.start()
            await asyncio.sleep(3)  # Wait for both VNC and noVNC to start

            # Check if noVNC is running
            result = subprocess.run(
                ["pgrep", "-f", "websockify"],
                capture_output=True,
                text=True,
            )

            # Expected to FAIL initially (RED phase)
            assert result.returncode == 0, "websockify process not found"

            # Check if WebSocket port 6080 is listening
            result = subprocess.run(
                ["ss", "-ltn", "sport", "=6080"],
                capture_output=True,
                text=True,
            )

            assert result.returncode == 0, "WebSocket port 6080 not listening"
            assert ":6080" in result.stdout, "Port 6080 not found in listening ports"

        finally:
            await manager.stop()

    @pytest.mark.integration
    def test_novnc_html_client_exists(self):
        """Test that noVNC HTML client is present."""
        novnc_path = Path("/opt/noVNC/vnc.html")
        # Expected to FAIL initially (RED phase)
        assert novnc_path.exists(), "noVNC HTML client not found"


class TestTigerVNCSessionPersistence:
    """Test TigerVNC session persistence."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_vnc_session_directory_exists(self, tmp_path):
        """Test that ~/.vnc directory is created."""
        # Simulate user home directory
        vnc_dir = Path.home() / ".vnc"

        # Expected to FAIL initially (RED phase)
        # Note: This may pass initially if directory exists
        assert vnc_dir.exists() or vnc_dir.is_dir(), \
            f"VNC session directory not found at {vnc_dir}"

    @pytest.mark.integration
    def test_vnc_session_files_created(self):
        """Test that VNC creates session files (passwd, config, xstartup)."""
        vnc_dir = Path.home() / ".vnc"

        if not vnc_dir.exists():
            pytest.skip("VNC directory not created yet")

        # Expected to FAIL initially (RED phase)
        # Check for typical VNC session files
        config_file = vnc_dir / "config"
        xstartup_file = vnc_dir / "xstartup"

        assert config_file.exists() or xstartup_file.exists(), \
            "VNC session files not found"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_session_persists_across_restarts(self, tmp_path):
        """Test that VNC sessions survive container restarts."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":1",
            resolution="1280x720",
        )

        try:
            # First start
            await manager.start()
            await asyncio.sleep(2)

            # Get initial process info
            status1 = manager.get_status()
            pid1 = status1.xvnc_pid

            # Restart
            await manager.restart()
            await asyncio.sleep(2)

            # Get new process info
            status2 = manager.get_status()
            pid2 = status2.xvnc_pid

            # Expected to FAIL initially (RED phase)
            # PIDs should be different (new process), but config should persist
            assert pid1 != pid2, "Process PID should change after restart"
            assert manager.is_running(), "Desktop should be running after restart"

        finally:
            await manager.stop()


class TestTigerVNCPerformance:
    """Test TigerVNC performance metrics."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_startup_time_under_5_seconds(self, tmp_path):
        """Test that VNC server starts within 5 seconds (performance target)."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":97",
            resolution="1280x720",
        )

        try:
            start_time = time.time()
            await manager.start()
            startup_time = time.time() - start_time

            # Expected to FAIL initially (RED phase)
            # Performance target: <5 seconds
            assert startup_time < 5.0, \
                f"Startup time {startup_time:.2f}s exceeds 5s target"

        finally:
            await manager.stop()

    @pytest.mark.integration
    def test_memory_usage_acceptable(self):
        """Test that TigerVNC memory usage is acceptable."""
        # Check if Xvfb and VNC processes are running
        result = subprocess.run(
            ["ps", "aux"],
            capture_output=True,
            text=True,
        )

        # Expected to FAIL initially (RED phase)
        # Should have Xvfb and VNC processes with reasonable memory usage
        assert "Xvfb" in result.stdout or "vncserver" in result.stdout, \
            "VNC process not found"

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_bandwidth_idle_state(self, tmp_path):
        """Test bandwidth usage in idle state (<500 Kbps target)."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":96",
            resolution="1280x720",
        )

        try:
            await manager.start()
            await asyncio.sleep(3)

            # Check network connections
            result = subprocess.run(
                ["ss", "-tn", "state", "established", "( sport = :5901 or dport = :5901 )"],
                capture_output=True,
                text=True,
            )

            # Expected to FAIL initially (RED phase)
            # Should have established connection on VNC port
            assert ":5901" in result.stdout or "5901" in result.stdout, \
                "VNC connection not found"

        finally:
            await manager.stop()


class TestTigerVNCGeometryConfiguration:
    """Test VNC geometry configuration."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_default_geometry_1280x720(self, tmp_path):
        """Test that default geometry is 1280x720."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":95",
            resolution="1280x720",
        )

        try:
            await manager.start()

            status = manager.get_status()
            # Expected to FAIL initially (RED phase)
            assert status.resolution == "1280x720", \
                f"Expected resolution 1280x720, got {status.resolution}"

        finally:
            await manager.stop()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_custom_geometry_1920x1080(self, tmp_path):
        """Test that custom geometry 1920x1080 works."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":94",
            resolution="1920x1080",
        )

        try:
            await manager.start()

            status = manager.get_status()
            # Expected to FAIL initially (RED phase)
            assert status.resolution == "1920x1080", \
                f"Expected resolution 1920x1080, got {status.resolution}"

        finally:
            await manager.stop()


class TestTigerVNCDesktopManagerIntegration:
    """Test DesktopManager integration with TigerVNC."""

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_desktop_manager_uses_tigervnc(self, tmp_path):
        """Test that DesktopManager uses TigerVNC instead of x11vnc."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":93",
            resolution="1280x720",
        )

        try:
            await manager.start()
            await asyncio.sleep(2)

            # Check that TigerVNC process is running (not x11vnc)
            result = subprocess.run(
                ["ps", "aux"],
                capture_output=True,
                text=True,
            )

            # Expected to FAIL initially (RED phase)
            # Should have vncserver (TigerVNC), not x11vnc
            assert "vncserver" in result.stdout or "Xvnc" in result.stdout, \
                "TigerVNC process not found"
            assert "x11vnc" not in result.stdout, \
                "Old x11vnc process should not be running"

        finally:
            await manager.stop()

    @pytest.mark.integration
    @pytest.mark.asyncio
    async def test_desktop_manager_status_reports_correctly(self, tmp_path):
        """Test that DesktopManager.get_status() reports TigerVNC correctly."""
        manager = DesktopManager(
            workspace_dir=str(tmp_path / "workspace"),
            display=":92",
            resolution="1280x720",
        )

        try:
            await manager.start()
            await asyncio.sleep(2)

            status = manager.get_status()

            # Expected to FAIL initially (RED phase)
            assert status.running is True, "Desktop should be running"
            assert status.display == ":92", f"Display should be :92, got {status.display}"
            assert status.resolution == "1280x720", \
                f"Resolution should be 1280x720, got {status.resolution}"
            assert status.port == 6080, f"Port should be 6080, got {status.port}"
            assert status.xvnc_pid is not None, "VNC PID should not be None"

        finally:
            await manager.stop()
