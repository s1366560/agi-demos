"""Desktop Manager for remote desktop (LXDE + noVNC).

Manages Xvfb, LXDE, x11vnc, and noVNC for browser-based remote desktop.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DesktopStatus:
    """Status of the remote desktop."""

    running: bool
    display: str
    resolution: str
    port: int
    xvfb_pid: Optional[int] = None
    xvnc_pid: Optional[int] = None


class DesktopManager:
    """
    Manages remote desktop environment.

    Provides browser-based remote desktop using:
    - Xvfb: Virtual X11 display
    - LXDE: Lightweight desktop environment
    - x11vnc: VNC server
    - noVNC: Web-based VNC client

    Usage:
        manager = DesktopManager(workspace_dir="/workspace")
        await manager.start()
        status = manager.get_status()
        await manager.stop()

        # Or use as context manager
        async with manager:
            # Desktop is running
            pass
    """

    def __init__(
        self,
        workspace_dir: str = "/workspace",
        display: str = ":1",
        resolution: str = "1280x720",
        port: int = 6080,
        host: str = "localhost",
    ):
        """
        Initialize the desktop manager.

        Args:
            workspace_dir: Working directory for desktop sessions
            display: X11 display number (e.g., ":1")
            resolution: Screen resolution (e.g., "1280x720")
            port: Port for noVNC web server
            host: Host for noVNC URL
        """
        self.workspace_dir = workspace_dir
        self.display = display
        self.resolution = resolution
        self.port = port
        self.host = host

        self.xvfb_process: Optional[asyncio.subprocess.Process] = None
        self.xvnc_process: Optional[asyncio.subprocess.Process] = None
        self.novnc_process: Optional[asyncio.subprocess.Process] = None

    def is_running(self) -> bool:
        """Check if desktop processes are running."""
        if self.xvfb_process is None:
            return False
        return (
            self.xvfb_process.returncode is None
            and (self.xvnc_process is None or self.xvnc_process.returncode is None)
        )

    async def start(self) -> None:
        """
        Start the remote desktop environment.

        Starts Xvfb, LXDE, x11vnc, and noVNC in sequence.

        Raises:
            RuntimeError: If desktop is already running
            FileNotFoundError: If required programs are not installed
        """
        if self.is_running():
            raise RuntimeError(f"Desktop is already running on {self.display}")

        logger.info(
            f"Starting desktop: display={self.display}, "
            f"resolution={self.resolution}, noVNC port={self.port}"
        )

        try:
            # Step 1: Start Xvfb (virtual display)
            await self._start_xvfb()

            # Step 2: Start LXDE desktop environment
            await self._start_lxde()

            # Step 3: Start x11vnc (VNC server)
            await self._start_xvnc()

            # Step 4: Start noVNC (websockify proxy)
            await self._start_novnc()

            logger.info(
                f"Desktop started: {self.display} -> http://{self.host}:{self.port}/vnc.html"
            )

        except FileNotFoundError:
            raise RuntimeError(
                "Desktop components not installed. "
                "Install with: apt-get install xorg lxde x11vnc"
            )

    async def _start_xvfb(self) -> None:
        """Start Xvfb virtual display."""
        logger.debug(f"Starting Xvfb on {self.display}")
        self.xvfb_process = await asyncio.create_subprocess_exec(
            "Xvfb",
            self.display,
            "-screen",
            "0",
            f"{self.resolution}x24",  # Width x Height x ColorDepth
            "-ac",  # Disable access control
            "-nolisten",
            "tcp",  # Disable TCP connections
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(1)  # Wait for Xvfb to initialize
        if not self.is_running():
            raise RuntimeError("Xvfb exited immediately")
        logger.debug(f"Xvfb started with PID {self.xvfb_process.pid}")

    async def _start_lxde(self) -> None:
        """Start LXDE desktop environment."""
        logger.debug("Starting LXDE")
        env = os.environ.copy()
        env["DISPLAY"] = self.display

        process = await asyncio.create_subprocess_exec(
            "startlxde",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # LXDE runs in background, we don't track it closely
        logger.debug(f"LXDE started with PID {process.pid}")

    async def _start_xvnc(self) -> None:
        """Start x11vnc VNC server."""
        logger.debug("Starting x11vnc")
        self.xvnc_process = await asyncio.create_subprocess_exec(
            "x11vnc",
            "-display",
            self.display,
            "-forever",  # Keep running after disconnect
            "-nopw",  # No password
            "-shared",  # Allow multiple connections
            "-xkb",  # Handle X keyboard events
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(1)  # Wait for x11vnc to initialize
        logger.debug(f"x11vnc started with PID {self.xvnc_process.pid}")

    async def _start_novnc(self) -> None:
        """Start noVNC websockify proxy."""
        logger.debug(f"Starting noVNC on port {self.port}")
        self.novnc_process = await asyncio.create_subprocess_exec(
            "/opt/noVNC/utils/novnc_proxy",
            "--vnc",
            f"localhost:{self._vnc_port}",
            "--listen",
            str(self.port),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await asyncio.sleep(2)  # Wait for noVNC to initialize
        logger.debug(f"noVNC started with PID {self.novnc_process.pid}")

    @property
    def _vnc_port(self) -> int:
        """Get the VNC port (5900 + display number)."""
        display_num = int(self.display.replace(":", ""))
        return 5900 + display_num

    async def stop(self) -> None:
        """
        Stop the remote desktop environment.

        Gracefully terminates all desktop processes.
        """
        logger.info("Stopping desktop")

        # Stop noVNC
        if self.novnc_process:
            try:
                self.novnc_process.terminate()
                try:
                    await asyncio.wait_for(self.novnc_process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.novnc_process.kill()
                    await self.novnc_process.wait()
            except Exception as e:
                logger.error(f"Error stopping noVNC: {e}")
            self.novnc_process = None

        # Stop x11vnc
        if self.xvnc_process:
            try:
                self.xvnc_process.terminate()
                try:
                    await asyncio.wait_for(self.xvnc_process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.xvnc_process.kill()
                    await self.xvnc_process.wait()
            except Exception as e:
                logger.error(f"Error stopping x11vnc: {e}")
            self.xvnc_process = None

        # Stop Xvfb
        if self.xvfb_process:
            try:
                self.xvfb_process.terminate()
                try:
                    await asyncio.wait_for(self.xvfb_process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.xvfb_process.kill()
                    await self.xvfb_process.wait()
            except Exception as e:
                logger.error(f"Error stopping Xvfb: {e}")
            self.xvfb_process = None

        logger.info("Desktop stopped")

    async def restart(self) -> None:
        """Restart the desktop environment."""
        await self.stop()
        await asyncio.sleep(1)  # Brief pause
        await self.start()

    def get_status(self) -> DesktopStatus:
        """
        Get current desktop status.

        Returns:
            DesktopStatus with current state
        """
        return DesktopStatus(
            running=self.is_running(),
            display=self.display,
            resolution=self.resolution,
            port=self.port,
            xvfb_pid=self.xvfb_process.pid if self.xvfb_process else None,
            xvnc_pid=self.xvnc_process.pid if self.xvnc_process else None,
        )

    def get_novnc_url(self) -> str:
        """
        Get the noVNC web client URL.

        Returns:
            URL string for accessing the desktop
        """
        return f"http://{self.host}:{self.port}/vnc.html"

    async def __aenter__(self):
        """Context manager entry - start desktop."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop desktop."""
        await self.stop()
        return False
