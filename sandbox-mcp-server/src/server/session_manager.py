"""Session Manager for unified terminal and desktop management.

Manages the lifecycle of web terminal and remote desktop sessions.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.server.desktop_manager import DesktopManager
from src.server.web_terminal import WebTerminalManager

logger = logging.getLogger(__name__)


@dataclass
class SessionStatus:
    """Status of all sessions."""

    terminal_running: bool
    desktop_running: bool
    terminal_port: int
    desktop_port: int
    terminal_pid: Optional[int] = None
    desktop_pid: Optional[int] = None


class SessionManager:
    """
    Unified manager for terminal and desktop sessions.

    Manages both WebTerminalManager and DesktopManager, providing
    a single interface for starting/stopping all sessions.

    Usage:
        manager = SessionManager(workspace_dir="/workspace")
        await manager.start_all()
        status = manager.get_status()
        await manager.stop_all()

        # Or use as context manager
        async with manager:
            # Sessions are running
            pass
    """

    def __init__(
        self,
        workspace_dir: str = "/workspace",
        terminal_port: int = 7681,
        desktop_port: int = 6080,
        terminal_enabled: bool = True,
        desktop_enabled: bool = True,
        host: str = "localhost",
    ):
        """
        Initialize the session manager.

        Args:
            workspace_dir: Working directory for sessions
            terminal_port: Port for ttyd WebSocket server
            desktop_port: Port for noVNC web server
            terminal_enabled: Whether to enable terminal on start
            desktop_enabled: Whether to enable desktop on start
            host: Host for URLs
        """
        self.workspace_dir = workspace_dir
        self.terminal_port = terminal_port
        self.desktop_port = desktop_port
        self.terminal_enabled = terminal_enabled
        self.desktop_enabled = desktop_enabled
        self.host = host

        # Create sub-managers
        self.terminal_manager = WebTerminalManager(
            workspace_dir=workspace_dir,
            port=terminal_port,
            host=host,
        )
        self.desktop_manager = DesktopManager(
            workspace_dir=workspace_dir,
            port=desktop_port,
            host=host,
        )

    async def start_all(self) -> None:
        """
        Start all enabled sessions.

        Starts terminal and desktop sessions based on enabled flags.
        Errors in one session do not prevent the other from starting.
        """
        logger.info("Starting all sessions...")

        # Start terminal if enabled
        if self.terminal_enabled:
            try:
                await self.terminal_manager.start()
                logger.info(f"Terminal started on port {self.terminal_port}")
            except Exception as e:
                logger.error(f"Failed to start terminal: {e}")
        else:
            logger.info("Terminal disabled, skipping")

        # Start desktop if enabled
        if self.desktop_enabled:
            try:
                await self.desktop_manager.start()
                logger.info(f"Desktop started on port {self.desktop_port}")
            except Exception as e:
                logger.error(f"Failed to start desktop: {e}")
        else:
            logger.info("Desktop disabled, skipping")

        logger.info("All sessions started")

    async def stop_all(self) -> None:
        """
        Stop all running sessions.

        Gracefully stops both terminal and desktop sessions.
        Errors in one session do not prevent the other from stopping.
        """
        logger.info("Stopping all sessions...")

        # Stop terminal
        try:
            if self.terminal_manager.is_running():
                await self.terminal_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping terminal: {e}")

        # Stop desktop
        try:
            if self.desktop_manager.is_running():
                await self.desktop_manager.stop()
        except Exception as e:
            logger.error(f"Error stopping desktop: {e}")

        logger.info("All sessions stopped")

    async def restart_all(self) -> None:
        """Restart all enabled sessions."""
        logger.info("Restarting all sessions...")
        await self.stop_all()
        await self.start_all()
        logger.info("All sessions restarted")

    def get_status(self) -> SessionStatus:
        """
        Get status of all sessions.

        Returns:
            SessionStatus with current state of all sessions
        """
        terminal_status = self.terminal_manager.get_status()
        desktop_status = self.desktop_manager.get_status()

        return SessionStatus(
            terminal_running=terminal_status.running,
            desktop_running=desktop_status.running,
            terminal_port=terminal_status.port,
            desktop_port=desktop_status.port,
            terminal_pid=terminal_status.pid,
            desktop_pid=desktop_status.xvfb_pid,
        )

    def get_terminal_info(self) -> dict:
        """
        Get terminal session information.

        Returns:
            Dictionary with terminal info
        """
        status = self.terminal_manager.get_status()
        return {
            "enabled": self.terminal_enabled,
            "running": status.running,
            "port": status.port,
            "url": self.terminal_manager.get_websocket_url(),
            "pid": status.pid,
        }

    def get_desktop_info(self) -> dict:
        """
        Get desktop session information.

        Returns:
            Dictionary with desktop info
        """
        status = self.desktop_manager.get_status()
        return {
            "enabled": self.desktop_enabled,
            "running": status.running,
            "port": status.port,
            "url": self.desktop_manager.get_novnc_url(),
            "display": self.desktop_manager.display,
            "resolution": self.desktop_manager.resolution,
            "pid": status.xvfb_pid,
        }

    async def __aenter__(self):
        """Context manager entry - start all sessions."""
        await self.start_all()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop all sessions."""
        await self.stop_all()
        return False
