"""Desktop Manager for remote desktop (XFCE + TigerVNC + noVNC).

Manages Xvfb, XFCE, TigerVNC, and noVNC for browser-based remote desktop.
TigerVNC provides better encoding and performance compared to x11vnc.
"""

import asyncio
import logging
import os
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class DesktopStatus:
    """Status of the remote desktop.

    Attributes:
        running: Whether desktop is currently running
        display: X11 display number (e.g., ":1")
        resolution: Screen resolution (e.g., "1280x720")
        port: noVNC web server port
        xvfb_pid: Process ID of Xvfb (None if not running)
        xvnc_pid: Process ID of TigerVNC (None if not running)
    """

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
    - XFCE: Lightweight desktop environment
    - TigerVNC: VNC server (better performance than x11vnc)
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

        Starts Xvfb, XFCE, TigerVNC, and noVNC in sequence.

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

            # Step 2: Start XFCE desktop environment
            await self._start_xfce()

            # Step 3: Start TigerVNC (VNC server)
            await self._start_tigervnc()

            # Step 4: Start noVNC (websockify proxy)
            await self._start_novnc()

            logger.info(
                f"Desktop started: {self.display} -> http://{self.host}:{self.port}/vnc.html"
            )

        except FileNotFoundError:
            raise RuntimeError(
                "Desktop components not installed. "
                "Install with: apt-get install xorg xfce4 tigervnc-standalone-server"
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

    async def _start_xfce(self) -> None:
        """Start XFCE desktop environment."""
        logger.debug("Starting XFCE")
        env = os.environ.copy()
        env["DISPLAY"] = self.display

        # Start XFCE session using xfce4-session
        process = await asyncio.create_subprocess_exec(
            "xfce4-session",
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        # XFCE runs in background, we don't track it closely
        logger.debug(f"XFCE started with PID {process.pid}")

    async def _start_tigervnc(self) -> None:
        """Start TigerVNC server with optimal settings."""
        logger.debug("Starting TigerVNC")

        # Prepare VNC user directory
        vnc_dir = os.path.expanduser("~/.vnc")
        os.makedirs(vnc_dir, exist_ok=True)

        # Create xstartup file if it doesn't exist
        xstartup_path = os.path.join(vnc_dir, "xstartup")
        if not os.path.exists(xstartup_path):
            # Copy template or create default
            template_path = "/etc/vnc/xstartup.template"
            if os.path.exists(template_path):
                import shutil
                shutil.copy(template_path, xstartup_path)
            else:
                # Create minimal xstartup
                with open(xstartup_path, "w") as f:
                    f.write("#!/bin/bash\n")
                    f.write(f"export DISPLAY={self.display}\n")
                    f.write("xfce4-session &\n")
                    f.write("wait\n")
            os.chmod(xstartup_path, 0o755)

        # Extract width and height from resolution
        width, height = self.resolution.split("x")
        depth = 24

        # Start TigerVNC with optimal settings
        # TigerVNC uses vncserver command which wraps Xvfb
        self.xvnc_process = await asyncio.create_subprocess_exec(
            "vncserver",
            self.display,
            "-geometry", self.resolution,
            "-depth", str(depth),
            "-encoding", "Tight",  # Best for web VNC
            "-compression", "5",    # Balance CPU/bandwidth
            "-quality", "8",        # Good image quality
            "-noxstartup",          # Don't use default xstartup
            "-rfbport", str(self._vnc_port),
            "-localhost", "no",     # Allow connections from any host
            "-securitytypes", "None",  # No authentication for container
            env=os.environ.copy(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        await asyncio.sleep(2)  # Wait for TigerVNC to initialize
        logger.debug(f"TigerVNC started with PID {self.xvnc_process.pid}")

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

        # Stop TigerVNC
        if self.xvnc_process:
            try:
                # Try graceful shutdown first
                self.xvnc_process.terminate()
                try:
                    await asyncio.wait_for(self.xvnc_process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Force kill if graceful shutdown fails
                    self.xvnc_process.kill()
                    await self.xvnc_process.wait()
            except Exception as e:
                logger.error(f"Error stopping TigerVNC: {e}")
            self.xvnc_process = None

        # Also try to kill any remaining vncserver processes
        try:
            await asyncio.create_subprocess_exec(
                "vncserver",
                "-kill",
                self.display,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except Exception as e:
            logger.debug(f"vncserver -kill command failed: {e}")

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
