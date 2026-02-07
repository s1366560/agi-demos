"""Process tracker for managed MCP server subprocesses.

Tracks running MCP server processes, monitors health,
and handles restart on crash.
"""

import asyncio
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ServerStatus(str, Enum):
    """Status of a managed MCP server."""

    INSTALLING = "installing"
    STARTING = "starting"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    CRASHED = "crashed"


@dataclass
class ManagedServer:
    """Tracks a managed MCP server process."""

    name: str
    server_type: str
    command: str
    args: List[str] = field(default_factory=list)
    env: Dict[str, str] = field(default_factory=dict)
    status: ServerStatus = ServerStatus.STOPPED
    process: Optional[asyncio.subprocess.Process] = None
    pid: Optional[int] = None
    port: Optional[int] = None
    started_at: Optional[datetime] = None
    error: Optional[str] = None
    restart_count: int = 0
    max_restarts: int = 3

    # For stdio servers: the stdin/stdout pipes are used for MCP protocol
    # For http/sse/websocket servers: a port is allocated

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "name": self.name,
            "server_type": self.server_type,
            "command": self.command,
            "args": self.args,
            "status": self.status.value,
            "pid": self.pid,
            "port": self.port,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "error": self.error,
            "restart_count": self.restart_count,
        }


class ProcessTracker:
    """Tracks and manages MCP server subprocesses."""

    def __init__(self) -> None:
        self._servers: Dict[str, ManagedServer] = {}
        self._monitor_tasks: Dict[str, asyncio.Task] = {}
        self._next_port = 9000  # Ports for http/sse/websocket servers

    def get_server(self, name: str) -> Optional[ManagedServer]:
        """Get a managed server by name."""
        return self._servers.get(name)

    def list_servers(self) -> List[ManagedServer]:
        """List all managed servers."""
        return list(self._servers.values())

    def allocate_port(self) -> int:
        """Allocate a port for an http/sse/websocket server."""
        port = self._next_port
        self._next_port += 1
        return port

    async def start_stdio_server(
        self,
        name: str,
        command: str,
        args: List[str],
        env: Dict[str, str],
        working_dir: str = "/workspace",
    ) -> ManagedServer:
        """Start a stdio-based MCP server subprocess.

        The process communicates via stdin/stdout using JSON-RPC.

        Args:
            name: Server name.
            command: Command to run.
            args: Command arguments.
            env: Environment variables.
            working_dir: Working directory.

        Returns:
            ManagedServer with process handle.
        """
        server = ManagedServer(
            name=name,
            server_type="stdio",
            command=command,
            args=args,
            env=env,
            status=ServerStatus.STARTING,
        )
        self._servers[name] = server

        try:
            full_cmd = [command] + args
            merged_env = {**os.environ, **env}

            process = await asyncio.create_subprocess_exec(
                *full_cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=merged_env,
                limit=10 * 1024 * 1024,  # 10MB for large MCP tool lists
            )

            server.process = process
            server.pid = process.pid
            server.status = ServerStatus.RUNNING
            server.started_at = datetime.utcnow()

            self._monitor_tasks[name] = asyncio.create_task(self._monitor_process(name))

            logger.info(f"Started stdio MCP server '{name}' (PID={process.pid})")
            return server

        except Exception as e:
            server.status = ServerStatus.FAILED
            server.error = str(e)
            logger.error(f"Failed to start MCP server '{name}': {e}")
            raise

    async def start_network_server(
        self,
        name: str,
        command: str,
        args: List[str],
        env: Dict[str, str],
        port: int,
        working_dir: str = "/workspace",
    ) -> ManagedServer:
        """Start a network-based MCP server (http/sse/websocket).

        The server listens on a localhost port.

        Args:
            name: Server name.
            command: Command to run.
            args: Command arguments.
            env: Environment variables.
            port: Port to listen on.
            working_dir: Working directory.

        Returns:
            ManagedServer with process handle.
        """
        server = ManagedServer(
            name=name,
            server_type="network",
            command=command,
            args=args,
            env=env,
            status=ServerStatus.STARTING,
            port=port,
        )
        self._servers[name] = server

        try:
            full_cmd = f"{command} {' '.join(args)}"
            merged_env = {**os.environ, **env, "PORT": str(port)}

            process = await asyncio.create_subprocess_shell(
                full_cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=working_dir,
                env=merged_env,
            )

            server.process = process
            server.pid = process.pid
            server.status = ServerStatus.RUNNING
            server.started_at = datetime.utcnow()

            self._monitor_tasks[name] = asyncio.create_task(self._monitor_process(name))

            logger.info(f"Started network MCP server '{name}' (PID={process.pid}, port={port})")
            return server

        except Exception as e:
            server.status = ServerStatus.FAILED
            server.error = str(e)
            logger.error(f"Failed to start MCP server '{name}': {e}")
            raise

    async def stop_server(self, name: str) -> bool:
        """Stop a managed MCP server.

        Args:
            name: Server name.

        Returns:
            True if stopped successfully.
        """
        server = self._servers.get(name)
        if not server:
            return False

        # Cancel monitor task
        monitor = self._monitor_tasks.pop(name, None)
        if monitor:
            monitor.cancel()
            try:
                await monitor
            except asyncio.CancelledError:
                pass

        # Terminate process
        proc = server.process
        if proc and proc.returncode is None:
            try:
                proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()
                logger.info(f"Stopped MCP server '{name}' (PID={server.pid})")
            except ProcessLookupError:
                pass

        server.status = ServerStatus.STOPPED
        server.process = None
        server.pid = None
        return True

    async def stop_all(self) -> None:
        """Stop all managed MCP servers."""
        names = list(self._servers.keys())
        for name in names:
            await self.stop_server(name)

    async def remove_server(self, name: str) -> bool:
        """Stop and remove a managed server from tracking."""
        await self.stop_server(name)
        return self._servers.pop(name, None) is not None

    async def _monitor_process(self, name: str) -> None:
        """Monitor a process and handle crashes."""
        server = self._servers.get(name)
        if not server or not server.process:
            return

        try:
            returncode = await server.process.wait()
            if server.status == ServerStatus.STOPPED:
                return  # Normal shutdown

            logger.warning(f"MCP server '{name}' exited with code {returncode}")
            server.status = ServerStatus.CRASHED
            server.error = f"Process exited with code {returncode}"

            # Read stderr for error details
            if server.process.stderr:
                try:
                    stderr = await server.process.stderr.read()
                    if stderr:
                        err_text = stderr.decode("utf-8", errors="replace")[:1000]
                        server.error += f": {err_text}"
                except Exception:
                    pass

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error monitoring MCP server '{name}': {e}")
