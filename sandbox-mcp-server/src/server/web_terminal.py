"""Web Terminal Manager for ttyd.

Manages ttyd subprocess to provide browser-based terminal access.
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class TerminalStatus:
    """Status of the web terminal."""

    running: bool
    port: int
    pid: Optional[int] = None


class WebTerminalManager:
    """
    Manages ttyd subprocess for web terminal access.

    Provides browser-based shell terminal using ttyd:
    https://github.com/tsl0922/ttyd

    Usage:
        manager = WebTerminalManager(workspace_dir="/workspace")
        await manager.start()
        status = manager.get_status()
        await manager.stop()

        # Or use as context manager
        async with manager:
            # Terminal is running
            pass
    """

    def __init__(
        self,
        workspace_dir: str = "/workspace",
        port: int = 7681,
        host: str = "localhost",
    ):
        """
        Initialize the web terminal manager.

        Args:
            workspace_dir: Working directory for terminal sessions
            port: Port for ttyd WebSocket server
            host: Host for ttyd WebSocket server
        """
        self.workspace_dir = workspace_dir
        self.port = port
        self.host = host
        self.process: Optional[asyncio.subprocess.Process] = None

    def is_running(self) -> bool:
        """Check if ttyd process is running.
        
        Checks both the managed process and system-wide for ttyd processes.
        This handles cases where ttyd was started by container entrypoint.
        """
        # First check our managed process
        if self.process is not None and self.process.returncode is None:
            return True
        
        # Check for system-wide process on our port using methods that don't require root
        import subprocess
        
        # Method 1: Check if port is in use via /proc/net/tcp (no root needed)
        try:
            # Convert port to hex for /proc/net/tcp lookup
            port_hex = f'{self.port:04X}'
            with open('/proc/net/tcp', 'r') as f:
                for line in f:
                    # Format: sl local_address remote_address st ...
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        local_addr = parts[1]
                        # local_address format: IP:PORT in hex
                        if ':' in local_addr:
                            addr_port = local_addr.split(':')[1]
                            if addr_port == port_hex:
                                return True
        except (FileNotFoundError, PermissionError, Exception):
            pass
        
        # Method 2: Try to connect to the port to see if it's accepting connections
        try:
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', self.port))
            sock.close()
            if result == 0:
                return True
        except Exception:
            pass
        
        return False

    async def start(self) -> None:
        """
        Start the ttyd server.

        Raises:
            RuntimeError: If ttyd is already running
            FileNotFoundError: If ttyd is not installed
        """
        if self.is_running():
            raise RuntimeError(f"Web terminal is already running on port {self.port}")

        logger.info(f"Starting ttyd on port {self.port}, workspace: {self.workspace_dir}")

        try:
            self.process = await asyncio.create_subprocess_exec(
                "ttyd",
                "-p", str(self.port),  # Port
                "-W",  # Enable Werkzeug-like path prefix handling
                "/bin/bash",
                cwd=self.workspace_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            logger.info(f"ttyd started with PID {self.process.pid}")

            # Give it a moment to start and verify it's running
            await asyncio.sleep(0.5)
            if not self.is_running():
                raise RuntimeError(f"ttyd process exited immediately")

        except FileNotFoundError:
            raise RuntimeError(
                "ttyd is not installed. Install it with: "
                "curl -fsSL https://github.com/tsl0922/ttyd/releases/download/1.7.4/ttyd.linux_$(uname -m).tar.gz | tar -xz -C /usr/local/bin"
            )

    async def stop(self, force_timeout: float = 5.0) -> None:
        """
        Stop the ttyd server.

        Args:
            force_timeout: Seconds to wait before force killing (SIGKILL)
        """
        if self.process is None:
            return

        logger.info(f"Stopping ttyd (PID {self.process.pid})")

        try:
            # Try graceful shutdown first
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=force_timeout)
            except asyncio.TimeoutError:
                logger.warning("ttyd did not stop gracefully, using SIGKILL")
                self.process.kill()
                await self.process.wait()

        except Exception as e:
            logger.error(f"Error stopping ttyd: {e}")
        finally:
            self.process = None
            logger.info("ttyd stopped")

    async def restart(self) -> None:
        """Restart the ttyd server."""
        await self.stop()
        await asyncio.sleep(0.5)  # Brief pause
        await self.start()

    def get_status(self) -> TerminalStatus:
        """
        Get current terminal status.

        Returns:
            TerminalStatus with current state
        """
        running = self.is_running()
        pid = self.process.pid if self.process else None
        
        # If no managed process but ttyd is running, try to get system PID
        if running and pid is None:
            pid = self._get_system_ttyd_pid()
        
        return TerminalStatus(
            running=running,
            port=self.port,
            pid=pid,
        )
    
    def _get_system_ttyd_pid(self) -> Optional[int]:
        """Get PID of system-wide ttyd process on our port."""
        import subprocess
        try:
            result = subprocess.run(
                ["netstat", "-tlnp"],
                capture_output=True,
                text=True,
                timeout=5
            )
            for line in result.stdout.split('\n'):
                if f":{self.port}" in line and 'ttyd' in line:
                    # Extract PID from the line (format: ... PID/ttyd)
                    parts = line.split()
                    for part in parts:
                        if '/ttyd' in part:
                            pid_str = part.split('/')[0]
                            if pid_str.isdigit():
                                return int(pid_str)
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
            pass
        return None

    def get_websocket_url(self) -> str:
        """
        Get the WebSocket URL for connecting to the terminal.

        Returns:
            WebSocket URL string
        """
        return f"ws://{self.host}:{self.port}"

    async def __aenter__(self):
        """Context manager entry - start terminal."""
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - stop terminal."""
        await self.stop()
        return False
