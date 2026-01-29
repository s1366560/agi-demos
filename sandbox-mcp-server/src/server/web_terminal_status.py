"""Web Terminal Status Query.

Simplified module that only provides status query for ttyd.
Service startup is managed by entrypoint.sh.
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TerminalStatus:
    """Status of the web terminal."""

    running: bool
    port: int
    pid: Optional[int] = None
    url: Optional[str] = None
    session_id: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "running": self.running,
            "port": self.port,
            "pid": self.pid,
            "url": self.url,
            "session_id": self.session_id,
        }


class WebTerminalStatus:
    """
    Status query interface for ttyd web terminal.

    Service startup is managed by entrypoint.sh.
    This class only provides status and health check functionality.

    Usage:
        status = WebTerminalStatus()
        is_running = status.is_running()
        info = status.get_status()
    """

    DEFAULT_PORT = 7681
    DEFAULT_HOST = "localhost"

    def __init__(
        self,
        port: int = DEFAULT_PORT,
        host: str = DEFAULT_HOST,
    ):
        """
        Initialize the terminal status checker.

        Args:
            port: Port where ttyd should be running
            host: Host where ttyd is running
        """
        self.port = port
        self.host = host
        self._pid: Optional[int] = None

    def is_running(self) -> bool:
        """Check if ttyd process is running.

        Returns:
            True if ttyd is running
        """
        # Check if process is running using PID file or process name
        pid = self._get_ttyd_pid()
        return pid is not None

    def get_status(self) -> TerminalStatus:
        """
        Get current terminal status.

        Returns:
            TerminalStatus with current state
        """
        pid = self._get_ttyd_pid()
        running = pid is not None

        url = None
        if running:
            url = f"ws://{self.host}:{self.port}"

        return TerminalStatus(
            running=running,
            port=self.port,
            pid=pid,
            url=url,
            session_id=None,  # Could be enhanced to track session
        )

    def get_port(self) -> int:
        """Get the terminal port."""
        return self.port

    def get_websocket_url(self) -> Optional[str]:
        """
        Get the WebSocket URL for connecting to the terminal.

        Returns:
            WebSocket URL string or None if not running
        """
        if self.is_running():
            return f"ws://{self.host}:{self.port}"
        return None

    def _get_ttyd_pid(self) -> Optional[int]:
        """Get the PID of the running ttyd process.

        Returns:
            PID of ttyd process or None if not running
        """
        # Use subprocess synchronously to avoid async issues in sync context
        try:
            import subprocess
            result = subprocess.run(
                ["lsof", "-i", f":{self.port}", "-t", "-P", "ttyd"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0 and result.stdout.strip():
                # Parse PID from lsof output
                parts = result.stdout.split()
                if parts:
                    try:
                        return int(parts[1])  # Second column is PID
                    except (ValueError, IndexError):
                        pass
        except (FileNotFoundError, OSError):
            pass

        return None

    async def health_check(self) -> bool:
        """
        Perform health check on ttyd service.

        Returns:
            True if service is healthy
        """
        if not self.is_running():
            return False

        # Try to connect to the WebSocket port
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.host,
                    self.port,
                ),
                timeout=2.0,
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError):
            return False


# Backward compatibility alias
WebTerminalManager = WebTerminalStatus
