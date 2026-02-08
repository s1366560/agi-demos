"""Desktop Manager for remote desktop (KDE Plasma + KasmVNC).

Manages KasmVNC for browser-based remote desktop with KDE Plasma.
KasmVNC is an all-in-one VNC server with built-in web client,
WebP encoding, dynamic resize, clipboard, file transfer, and audio.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DesktopStatus:
    """Status of the remote desktop.

    Attributes:
        running: Whether desktop is currently running
        display: X11 display number (e.g., ":1")
        resolution: Screen resolution (e.g., "1920x1080")
        port: KasmVNC web server port
        kasmvnc_pid: Process ID of KasmVNC (None if not running)
        audio_enabled: Whether audio streaming is available
        dynamic_resize: Whether dynamic resize is supported
        encoding: Current encoding method
    """

    running: bool
    display: str
    resolution: str
    port: int
    kasmvnc_pid: Optional[int] = None
    audio_enabled: bool = True
    dynamic_resize: bool = True
    encoding: str = "webp"


class DesktopManager:
    """
    Manages remote desktop environment using KasmVNC.

    KasmVNC replaces the previous TigerVNC + noVNC + websockify stack
    with a single all-in-one process that provides:
    - X server (built-in, no separate Xvfb needed)
    - VNC server with WebP/QOI/JPEG encoding
    - WebSocket server with built-in web client
    - Dynamic resolution resize
    - Bi-directional clipboard (text + images)
    - File transfer (drag-drop upload/download)
    - Audio streaming via PulseAudio

    Usage:
        manager = DesktopManager(workspace_dir="/workspace")
        await manager.start()
        status = manager.get_status()
        await manager.change_resolution("1920x1080")
        await manager.stop()
    """

    def __init__(
        self,
        workspace_dir: str = "/workspace",
        display: str = ":1",
        resolution: str = "1920x1080",
        port: int = 6080,
        host: str = "localhost",
    ):
        self.workspace_dir = workspace_dir
        self.display = display
        self.resolution = resolution
        self.port = port
        self.host = host

        self._kasmvnc_started: bool = False

    def _is_port_listening(self, port: int) -> bool:
        """Check if a port is listening."""
        import socket
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(0.5)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            return result == 0
        except Exception:
            return False

    def _get_kasmvnc_pid(self) -> Optional[int]:
        """Get the PID of the KasmVNC process."""
        try:
            import subprocess
            result = subprocess.run(
                ['pgrep', '-f', 'Xkasmvnc'],
                capture_output=True, text=True, timeout=2
            )
            if result.returncode == 0 and result.stdout.strip():
                return int(result.stdout.strip().split()[0])
        except Exception as e:
            logger.debug(f"Failed to get KasmVNC PID: {e}")
        return None

    def is_running(self) -> bool:
        """Check if KasmVNC is running."""
        if self._kasmvnc_started:
            return self._is_port_listening(self.port)
        # Check system-wide
        return self._is_port_listening(self.port) or self._get_kasmvnc_pid() is not None

    async def start(self) -> None:
        """
        Start the remote desktop environment.

        Starts KasmVNC which provides X server + VNC + web client all-in-one.

        Raises:
            RuntimeError: If desktop is already running
        """
        if self.is_running():
            raise RuntimeError(f"Desktop is already running on {self.display}")

        logger.info(
            f"Starting KasmVNC desktop: display={self.display}, "
            f"resolution={self.resolution}, port={self.port}"
        )

        try:
            # Prepare VNC user directory
            vnc_dir = os.path.expanduser("~/.vnc")
            os.makedirs(vnc_dir, exist_ok=True)

            # Ensure KasmVNC user exists with write permissions
            # KasmVNC reads $HOME/.kasmpasswd (NOT .vnc/kasmpasswd)
            kasmpasswd_path = os.path.expanduser("~/.kasmpasswd")
            if not os.path.exists(kasmpasswd_path):
                with open(kasmpasswd_path, "w") as f:
                    f.write("root:kasmvnc:ow\n")
                os.chmod(kasmpasswd_path, 0o600)

            # Copy xstartup from template if needed
            xstartup_path = os.path.join(vnc_dir, "xstartup")
            template_path = "/etc/kasmvnc/xstartup.template"
            if os.path.exists(template_path):
                import shutil
                shutil.copy(template_path, xstartup_path)
                os.chmod(xstartup_path, 0o755)

            # Mark DE as selected to skip interactive select-de.sh
            de_marker = os.path.join(vnc_dir, ".de-was-selected")
            if not os.path.exists(de_marker):
                with open(de_marker, "w") as f:
                    pass

            env = os.environ.copy()
            env["DISPLAY"] = self.display

            # Start KasmVNC (single process replaces Xvfb + TigerVNC + websockify)
            process = await asyncio.create_subprocess_exec(
                "vncserver",
                self.display,
                "-geometry", self.resolution,
                "-depth", "24",
                "-websocketPort", str(self.port),
                "-interface", "0.0.0.0",
                "-disableBasicAuth",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            # Wait for KasmVNC to initialize
            for _ in range(15):
                await asyncio.sleep(1)
                if self._is_port_listening(self.port):
                    break

            if not self._is_port_listening(self.port):
                raise RuntimeError("KasmVNC failed to start within timeout")

            self._kasmvnc_started = True
            logger.info(
                f"KasmVNC started: {self.display} -> http://{self.host}:{self.port}"
            )

        except FileNotFoundError:
            raise RuntimeError(
                "KasmVNC not installed. Install with: apt-get install kasmvncserver"
            )

    async def stop(self) -> None:
        """Stop the remote desktop environment."""
        logger.info("Stopping KasmVNC desktop")

        try:
            process = await asyncio.create_subprocess_exec(
                "vncserver", "-kill", self.display,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            try:
                await asyncio.wait_for(process.wait(), timeout=10.0)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
        except Exception as e:
            logger.error(f"Error stopping KasmVNC: {e}")

        self._kasmvnc_started = False
        logger.info("KasmVNC desktop stopped")

    async def restart(self) -> None:
        """Restart the desktop environment."""
        await self.stop()
        await asyncio.sleep(1)
        await self.start()

    async def change_resolution(self, resolution: str) -> bool:
        """
        Change desktop resolution dynamically (no restart needed).

        KasmVNC supports live resolution changes via xrandr.

        Args:
            resolution: New resolution (e.g., "1920x1080")

        Returns:
            True if resolution was changed successfully
        """
        if not self.is_running():
            logger.warning("Cannot change resolution: desktop not running")
            return False

        try:
            width, height = resolution.split("x")
            env = os.environ.copy()
            env["DISPLAY"] = self.display

            # Use xrandr to change resolution dynamically
            process = await asyncio.create_subprocess_exec(
                "xrandr", "--output", "default", "--mode", f"{width}x{height}",
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=5.0)

            if process.returncode == 0:
                self.resolution = resolution
                logger.info(f"Resolution changed to {resolution}")
                return True
            else:
                # Try adding the mode first, then setting it
                process = await asyncio.create_subprocess_exec(
                    "xrandr", "-s", resolution,
                    env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(process.communicate(), timeout=5.0)
                if process.returncode == 0:
                    self.resolution = resolution
                    logger.info(f"Resolution changed to {resolution}")
                    return True

                logger.warning(f"Failed to change resolution: {stderr.decode()}")
                return False

        except Exception as e:
            logger.error(f"Error changing resolution: {e}")
            return False

    def get_status(self) -> DesktopStatus:
        """Get current desktop status."""
        return DesktopStatus(
            running=self.is_running(),
            display=self.display,
            resolution=self.resolution,
            port=self.port,
            kasmvnc_pid=self._get_kasmvnc_pid(),
            audio_enabled=True,
            dynamic_resize=True,
            encoding="webp",
        )

    def get_web_url(self) -> str:
        """Get the KasmVNC web client URL."""
        return f"http://{self.host}:{self.port}"

    async def __aenter__(self):
        """Context manager entry - start desktop."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop desktop."""
        await self.stop()
        return False
