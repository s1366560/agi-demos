"""Terminal Proxy - Docker exec TTY proxy for interactive shell.

Provides bidirectional communication between WebSocket clients and
Docker container interactive shells via docker exec.
"""

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import docker
from docker.errors import NotFound

logger = logging.getLogger(__name__)


@dataclass
class TerminalSession:
    """Represents an active terminal session."""

    session_id: str
    container_id: str
    exec_id: str
    socket: Any  # Docker socket connection
    cols: int = 80
    rows: int = 24
    is_active: bool = True


class TerminalProxy:
    """
    Docker exec TTY proxy for interactive shell sessions.

    Creates and manages interactive shell sessions inside Docker containers,
    providing bidirectional communication for terminal emulators.

    Usage:
        proxy = TerminalProxy()

        # Create session
        session = await proxy.create_session(container_id)

        # Send input
        await proxy.send_input(session.session_id, "ls -la\\n")

        # Read output (async generator)
        async for output in proxy.read_output(session.session_id):
            print(output)

        # Resize terminal
        await proxy.resize(session.session_id, cols=120, rows=40)

        # Close session
        await proxy.close_session(session.session_id)
    """

    def __init__(self) -> None:
        """Initialize terminal proxy."""
        self._docker = docker.from_env()
        self._sessions: dict[str, TerminalSession] = {}
        self._output_callbacks: dict[str, Callable[[str], None]] = {}

    async def create_session(
        self,
        container_id: str,
        shell: str = "/bin/bash",
        cols: int = 80,
        rows: int = 24,
        env: dict[str, str] | None = None,
    ) -> TerminalSession:
        """
        Create a new interactive terminal session.

        Args:
            container_id: Docker container ID or name
            shell: Shell to execute (default: /bin/bash)
            cols: Terminal columns
            rows: Terminal rows
            env: Additional environment variables

        Returns:
            TerminalSession instance

        Raises:
            ValueError: If container not found
        """
        try:
            container = self._docker.containers.get(container_id)
        except NotFound:
            raise ValueError(f"Container not found: {container_id}")

        # Build environment
        exec_env = {
            "TERM": "xterm-256color",
            "COLUMNS": str(cols),
            "LINES": str(rows),
        }
        if env:
            exec_env.update(env)

        # Create exec instance with TTY
        exec_id = container.client.api.exec_create(
            container.id,
            shell,
            stdin=True,
            stdout=True,
            stderr=True,
            tty=True,
            environment=exec_env,
        )["Id"]

        # Start exec with socket mode
        socket = container.client.api.exec_start(
            exec_id,
            socket=True,
            tty=True,
        )

        # Resize to initial size
        try:
            container.client.api.exec_resize(exec_id, height=rows, width=cols)
        except Exception as e:
            logger.warning(f"Failed to resize terminal: {e}")

        # Create session
        import uuid

        session_id = str(uuid.uuid4())[:12]
        session = TerminalSession(
            session_id=session_id,
            container_id=container_id,
            exec_id=exec_id,
            socket=socket,
            cols=cols,
            rows=rows,
        )

        self._sessions[session_id] = session
        logger.info(f"Created terminal session {session_id} for container {container_id}")

        return session

    async def send_input(self, session_id: str, data: str) -> bool:
        """
        Send input to terminal session.

        Args:
            session_id: Terminal session ID
            data: Input data (string)

        Returns:
            True if sent successfully
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return False

        try:
            # Send data to socket
            socket = session.socket._sock
            await asyncio.to_thread(socket.send, data.encode())
            return True
        except Exception as e:
            logger.error(f"Failed to send input to session {session_id}: {e}")
            session.is_active = False
            return False

    async def read_output(self, session_id: str, chunk_size: int = 4096) -> str | None:
        """
        Read output from terminal session (single read).

        Args:
            session_id: Terminal session ID
            chunk_size: Maximum bytes to read

        Returns:
            Output string or None if session closed
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return None

        try:
            socket = session.socket._sock
            socket.setblocking(False)

            try:
                data = await asyncio.to_thread(socket.recv, chunk_size)
                if not data:
                    session.is_active = False
                    return None
                return data.decode("utf-8", errors="replace")
            except BlockingIOError:
                return ""
            except Exception as e:
                logger.error(f"Read error for session {session_id}: {e}")
                session.is_active = False
                return None

        except Exception as e:
            logger.error(f"Failed to read from session {session_id}: {e}")
            return None

    async def resize(self, session_id: str, cols: int, rows: int) -> bool:
        """
        Resize terminal window.

        Args:
            session_id: Terminal session ID
            cols: New column count
            rows: New row count

        Returns:
            True if resized successfully
        """
        session = self._sessions.get(session_id)
        if not session or not session.is_active:
            return False

        try:
            container = self._docker.containers.get(session.container_id)
            container.client.api.exec_resize(session.exec_id, height=rows, width=cols)
            session.cols = cols
            session.rows = rows
            return True
        except Exception as e:
            logger.error(f"Failed to resize session {session_id}: {e}")
            return False

    async def close_session(self, session_id: str) -> bool:
        """
        Close terminal session.

        Args:
            session_id: Terminal session ID

        Returns:
            True if closed successfully
        """
        session = self._sessions.pop(session_id, None)
        if not session:
            return False

        session.is_active = False

        try:
            # Close socket
            if session.socket:
                session.socket._sock.close()
            logger.info(f"Closed terminal session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Error closing session {session_id}: {e}")
            return False

    def get_session(self, session_id: str) -> TerminalSession | None:
        """Get terminal session by ID."""
        return self._sessions.get(session_id)

    def is_session_active(self, session_id: str) -> bool:
        """Check if session is active."""
        session = self._sessions.get(session_id)
        return session is not None and session.is_active

    async def cleanup_inactive(self) -> int:
        """
        Clean up inactive sessions.

        Returns:
            Number of sessions cleaned up
        """
        inactive = [sid for sid, s in self._sessions.items() if not s.is_active]
        for sid in inactive:
            await self.close_session(sid)
        return len(inactive)


# Global singleton instance
_terminal_proxy: TerminalProxy | None = None


def get_terminal_proxy() -> TerminalProxy:
    """Get or create the terminal proxy singleton."""
    global _terminal_proxy
    if _terminal_proxy is None:
        _terminal_proxy = TerminalProxy()
    return _terminal_proxy
