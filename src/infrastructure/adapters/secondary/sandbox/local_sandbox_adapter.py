"""Local Sandbox Adapter - Connects to sandboxes running on user's local machine.

This adapter connects to sandbox MCP servers running on the user's computer
(via WebSocket tunnel like ngrok or cloudflare) instead of cloud Docker containers.

Key features:
- WebSocket connection to local sandbox via tunnel URL
- Token-based authentication for secure connections
- Health monitoring and automatic reconnection
- Support for all standard MCP tools (file operations, terminal, desktop)

Use case: User wants to run agent tasks on their local files/environment
while using the MemStack platform for orchestration.
"""

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from src.domain.model.sandbox.project_sandbox import (
    LocalSandboxConfig,
)
from src.domain.ports.services.sandbox_port import (
    CodeExecutionRequest,
    CodeExecutionResult,
    SandboxConfig,
    SandboxInstance,
    SandboxPort,
    SandboxProvider,
    SandboxStatus,
)
from src.infrastructure.mcp.clients.websocket_client import (
    MCPWebSocketClient as WebSocketMCPClient,
)

logger = logging.getLogger(__name__)


@dataclass
class LocalSandboxConnection:
    """Represents a connection to a local sandbox."""

    sandbox_id: str
    project_id: str
    tenant_id: str
    tunnel_url: str
    workspace_path: str
    status: SandboxStatus = SandboxStatus.CREATING
    client: WebSocketMCPClient | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    last_activity_at: datetime | None = None
    error_message: str | None = None
    auth_token: str | None = None


class LocalSandboxAdapter(SandboxPort):
    """
    Adapter for connecting to local sandboxes on user's machine.

    Instead of managing Docker containers, this adapter connects to
    sandbox MCP servers running locally on the user's computer via
    WebSocket tunnels (ngrok, cloudflare tunnel, etc.).

    The user runs a local sandbox application (Electron app or CLI)
    that:
    1. Starts the sandbox-mcp-server locally
    2. Establishes a WebSocket tunnel (ngrok/cloudflare)
    3. Registers the tunnel URL with MemStack platform

    This adapter then connects to that tunnel URL to communicate
    with the local sandbox.

    Enhanced Features:
    - Automatic heartbeat to detect connection loss
    - Exponential backoff reconnection
    - Configurable retry limits
    - Connection state callbacks
    """

    def __init__(
        self,
        connection_timeout: int = 30,
        healthcheck_interval: int = 60,
        heartbeat_interval: int = 30,
        max_reconnect_attempts: int = 5,
        reconnect_backoff_base: float = 2.0,
        reconnect_backoff_max: float = 60.0,
    ) -> None:
        """
        Initialize the local sandbox adapter.

        Args:
            connection_timeout: Timeout for establishing connections (seconds)
            healthcheck_interval: Interval between health checks (seconds)
            heartbeat_interval: Interval for WebSocket heartbeat (seconds)
            max_reconnect_attempts: Maximum automatic reconnection attempts
            reconnect_backoff_base: Base delay for exponential backoff
            reconnect_backoff_max: Maximum backoff delay
        """
        self._connection_timeout = connection_timeout
        self._healthcheck_interval = healthcheck_interval
        self._heartbeat_interval = heartbeat_interval
        self._max_reconnect_attempts = max_reconnect_attempts
        self._reconnect_backoff_base = reconnect_backoff_base
        self._reconnect_backoff_max = reconnect_backoff_max

        self._connections: dict[str, LocalSandboxConnection] = {}
        self._health_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._reconnect_tasks: dict[str, asyncio.Task] = {}
        self._reconnect_attempts: dict[str, int] = {}
        self._running = False

        # Callbacks for connection state changes
        self._on_disconnect_callbacks: list[Callable] = []
        self._on_reconnect_callbacks: list[Callable] = []

    async def start(self) -> None:
        """Start the adapter and health monitoring."""
        self._running = True
        self._health_task = asyncio.create_task(
            self._health_monitor(),
            name="local-sandbox-health",
        )
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(),
            name="local-sandbox-heartbeat",
        )
        logger.info("LocalSandboxAdapter started with enhanced health monitoring")

    async def stop(self) -> None:
        """Stop the adapter and close all connections."""
        self._running = False

        # Cancel health and heartbeat tasks
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task

        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._heartbeat_task

        # Cancel all reconnect tasks
        for task in self._reconnect_tasks.values():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._reconnect_tasks.clear()
        self._reconnect_attempts.clear()

        # Close all connections
        for conn in list(self._connections.values()):
            await self._disconnect(conn)

        self._connections.clear()
        logger.info("LocalSandboxAdapter stopped")

    def on_disconnect(self, callback: Callable) -> "LocalSandboxAdapter":
        """Register callback for when a connection is lost."""
        self._on_disconnect_callbacks.append(callback)
        return self

    def on_reconnect(self, callback: Callable) -> "LocalSandboxAdapter":
        """Register callback for when a connection is restored."""
        self._on_reconnect_callbacks.append(callback)
        return self

    async def connect_to_local_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        local_config: LocalSandboxConfig,
        auth_token: str | None = None,
    ) -> LocalSandboxConnection:
        """
        Connect to a local sandbox via tunnel URL.

        Args:
            project_id: Project ID for this sandbox
            tenant_id: Tenant ID for multi-tenant isolation
            local_config: Local sandbox configuration with tunnel URL
            auth_token: Authentication token for the connection

        Returns:
            LocalSandboxConnection with connection details

        Raises:
            ConnectionError: If connection fails
        """
        sandbox_id = f"local-{project_id}-{uuid4().hex[:8]}"

        # Get the WebSocket URL
        ws_url = local_config.get_websocket_url()
        if not ws_url:
            raise ConnectionError("No tunnel URL configured for local sandbox")

        # Add auth token to URL if provided
        if auth_token:
            separator = "&" if "?" in ws_url else "?"
            ws_url = f"{ws_url}{separator}token={auth_token}"

        logger.info(f"Connecting to local sandbox: {ws_url} for project {project_id}")

        # Create connection record
        connection = LocalSandboxConnection(
            sandbox_id=sandbox_id,
            project_id=project_id,
            tenant_id=tenant_id,
            tunnel_url=ws_url,
            workspace_path=local_config.workspace_path,
            auth_token=auth_token,
        )

        try:
            # Create WebSocket MCP client
            client = WebSocketMCPClient(ws_url)
            await asyncio.wait_for(
                client.connect(),
                timeout=self._connection_timeout,
            )

            # Initialize MCP session
            await client.initialize()

            connection.client = client
            connection.status = SandboxStatus.RUNNING
            connection.last_activity_at = datetime.now(UTC)

            self._connections[sandbox_id] = connection
            logger.info(f"Connected to local sandbox {sandbox_id}")

            return connection

        except TimeoutError:
            connection.status = SandboxStatus.ERROR
            connection.error_message = "Connection timeout"
            raise ConnectionError(f"Timeout connecting to local sandbox: {ws_url}") from None

        except Exception as e:
            connection.status = SandboxStatus.ERROR
            connection.error_message = str(e)
            logger.error(f"Failed to connect to local sandbox: {e}")
            raise ConnectionError(f"Failed to connect to local sandbox: {e}") from e

    async def _disconnect(self, connection: LocalSandboxConnection) -> None:
        """Disconnect from a local sandbox."""
        if connection.client:
            try:
                await connection.client.disconnect()
            except Exception as e:
                logger.warning(f"Error closing connection {connection.sandbox_id}: {e}")
            connection.client = None
        connection.status = SandboxStatus.TERMINATED

    async def _health_monitor(self) -> None:
        """Monitor health of all local sandbox connections."""
        while self._running:
            try:
                await asyncio.sleep(self._healthcheck_interval)

                for sandbox_id, conn in list(self._connections.items()):
                    if conn.status != SandboxStatus.RUNNING:
                        continue

                    try:
                        # Try a simple ping/health check
                        if conn.client:
                            # MCP clients typically support ping
                            await asyncio.wait_for(
                                conn.client.call_tool("ping", {}),
                                timeout=5,
                            )
                            conn.last_activity_at = datetime.now(UTC)
                    except Exception as e:
                        logger.warning(f"Health check failed for {sandbox_id}: {e}")
                        await self._handle_connection_lost(sandbox_id, f"Health check failed: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in health monitor: {e}")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats to detect connection loss quickly."""
        while self._running:
            try:
                await asyncio.sleep(self._heartbeat_interval)

                for sandbox_id, conn in list(self._connections.items()):
                    if conn.status != SandboxStatus.RUNNING:
                        continue

                    if not conn.client:
                        continue

                    try:
                        # Send WebSocket ping
                        if hasattr(conn.client, "_ws") and conn.client._ws:
                            await asyncio.wait_for(
                                conn.client._ws.ping(),
                                timeout=10,
                            )
                        elif hasattr(conn.client, "ping"):
                            await asyncio.wait_for(
                                conn.client.ping(),
                                timeout=10,
                            )
                    except Exception as e:
                        logger.warning(f"Heartbeat failed for {sandbox_id}: {e}")
                        await self._handle_connection_lost(sandbox_id, f"Heartbeat failed: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in heartbeat loop: {e}")

    async def _handle_connection_lost(self, sandbox_id: str, reason: str) -> None:
        """Handle when a connection is lost."""
        conn = self._connections.get(sandbox_id)
        if not conn:
            return

        # Update status
        conn.status = SandboxStatus.ERROR
        conn.error_message = reason

        logger.warning(f"Connection lost for {sandbox_id}: {reason}")

        # Notify callbacks
        for callback in self._on_disconnect_callbacks:
            try:
                if asyncio.iscoroutinefunction(callback):
                    await callback(sandbox_id, reason)
                else:
                    callback(sandbox_id, reason)
            except Exception as e:
                logger.error(f"Error in disconnect callback: {e}")

        # Start auto-reconnect if not already in progress
        if sandbox_id not in self._reconnect_tasks:
            self._reconnect_tasks[sandbox_id] = asyncio.create_task(
                self._auto_reconnect(sandbox_id),
                name=f"reconnect-{sandbox_id}",
            )

    async def _auto_reconnect(self, sandbox_id: str) -> None:
        """Automatically attempt to reconnect with exponential backoff."""
        conn = self._connections.get(sandbox_id)
        if not conn:
            return

        # Initialize attempt counter
        self._reconnect_attempts[sandbox_id] = 0

        while self._running and sandbox_id in self._connections:
            attempts = self._reconnect_attempts.get(sandbox_id, 0)

            if attempts >= self._max_reconnect_attempts:
                logger.error(
                    f"Max reconnection attempts ({self._max_reconnect_attempts}) "
                    f"reached for {sandbox_id}"
                )
                conn.status = SandboxStatus.TERMINATED
                conn.error_message = "Max reconnection attempts exceeded"
                break

            # Calculate backoff with jitter
            import random

            backoff = min(
                self._reconnect_backoff_base * (2**attempts) + random.uniform(0, 1),
                self._reconnect_backoff_max,
            )

            logger.info(
                f"Reconnect attempt {attempts + 1}/{self._max_reconnect_attempts} "
                f"for {sandbox_id} in {backoff:.1f}s"
            )

            await asyncio.sleep(backoff)
            self._reconnect_attempts[sandbox_id] = attempts + 1

            # Attempt reconnection
            success = await self.reconnect(sandbox_id)
            if success:
                logger.info(f"Successfully reconnected to {sandbox_id}")
                self._reconnect_attempts.pop(sandbox_id, None)

                # Notify callbacks
                for callback in self._on_reconnect_callbacks:
                    try:
                        if asyncio.iscoroutinefunction(callback):
                            await callback(sandbox_id)
                        else:
                            callback(sandbox_id)
                    except Exception as e:
                        logger.error(f"Error in reconnect callback: {e}")

                break

        # Cleanup
        self._reconnect_tasks.pop(sandbox_id, None)

    # --- SandboxPort Interface Implementation ---

    async def create_sandbox(
        self,
        project_path: str,
        config: SandboxConfig | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> SandboxInstance:
        """
        Create a sandbox connection (for local sandboxes, this means connect).

        Note: For local sandboxes, the sandbox is already running on user's machine.
        This method connects to it rather than creating a new container.

        For actual sandbox creation, use connect_to_local_sandbox() directly.
        """
        raise NotImplementedError(
            "LocalSandboxAdapter does not create sandboxes. "
            "Use connect_to_local_sandbox() to connect to an existing local sandbox."
        )

    async def get_sandbox(self, sandbox_id: str) -> SandboxInstance | None:
        """Get the status of a local sandbox connection."""
        conn = self._connections.get(sandbox_id)
        if not conn:
            return None

        return SandboxInstance(
            id=conn.sandbox_id,
            status=conn.status,
            config=SandboxConfig(
                image="local-sandbox",
                provider=SandboxProvider.DOCKER,  # Technically not Docker, but compatible
            ),
            project_path=conn.workspace_path,
            endpoint=conn.tunnel_url,
            created_at=conn.created_at,
            error_message=conn.error_message,
            last_activity_at=conn.last_activity_at,
            labels={
                "project_id": conn.project_id,
                "tenant_id": conn.tenant_id,
                "sandbox_type": "local",
            },
        )

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Disconnect from a local sandbox."""
        conn = self._connections.get(sandbox_id)
        if not conn:
            return False

        await self._disconnect(conn)
        del self._connections[sandbox_id]
        logger.info(f"Disconnected from local sandbox {sandbox_id}")
        return True

    async def execute_code(
        self,
        request: CodeExecutionRequest,
    ) -> CodeExecutionResult:
        """Execute code in a local sandbox."""
        conn = self._connections.get(request.sandbox_id)
        if not conn or not conn.client:
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr="Sandbox not connected",
                exit_code=-1,
                execution_time_ms=0,
                error="Sandbox not connected",
            )

        try:
            start_time = datetime.now(UTC)

            # Use bash tool to execute code
            result = await conn.client.call_tool(
                "bash",
                {
                    "command": request.code,
                    "working_directory": request.working_directory,
                    "timeout": request.timeout_seconds or 30,
                },
            )

            execution_time = int((datetime.now(UTC) - start_time).total_seconds() * 1000)
            conn.last_activity_at = datetime.now(UTC)

            # Parse result
            content = result.get("content", [])
            text_content = ""
            for item in content:
                if item.get("type") == "text":
                    text_content += item.get("text", "")

            return CodeExecutionResult(
                success=not result.get("isError", False),
                stdout=text_content,
                stderr="",
                exit_code=0 if not result.get("isError") else 1,
                execution_time_ms=execution_time,
            )

        except Exception as e:
            logger.error(f"Error executing code in local sandbox: {e}")
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                execution_time_ms=0,
                error=str(e),
            )

    async def stream_execute(
        self,
        request: CodeExecutionRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute code with streaming output."""
        # For simplicity, use non-streaming execution
        result = await self.execute_code(request)

        yield {"type": "stdout", "data": result.stdout}
        if result.stderr:
            yield {"type": "stderr", "data": result.stderr}
        yield {
            "type": "status",
            "data": {
                "success": result.success,
                "exit_code": result.exit_code,
            },
        }

    async def list_sandboxes(
        self,
        status: SandboxStatus | None = None,
    ) -> list[SandboxInstance]:
        """List all local sandbox connections."""
        instances = []
        for conn in self._connections.values():
            if status and conn.status != status:
                continue

            instance = await self.get_sandbox(conn.sandbox_id)
            if instance:
                instances.append(instance)

        return instances

    async def get_output_files(
        self,
        sandbox_id: str,
        pattern: str = "*",
    ) -> list[dict[str, Any]]:
        """Get output files from local sandbox."""
        conn = self._connections.get(sandbox_id)
        if not conn or not conn.client:
            return []

        try:
            result = await conn.client.call_tool(
                "glob",
                {
                    "pattern": pattern,
                    "path": conn.workspace_path,
                },
            )

            content = result.get("content", [])
            files = []
            for item in content:
                if item.get("type") == "text":
                    # Parse file list from text
                    text = item.get("text", "")
                    for line in text.strip().split("\n"):
                        if line:
                            files.append({"path": line})

            return files

        except Exception as e:
            logger.error(f"Error listing files in local sandbox: {e}")
            return []

    async def read_file(
        self,
        sandbox_id: str,
        file_path: str,
    ) -> str | None:
        """Read a file from local sandbox."""
        conn = self._connections.get(sandbox_id)
        if not conn or not conn.client:
            return None

        try:
            result = await conn.client.call_tool(
                "read",
                {"file_path": file_path},
            )

            content = result.get("content", [])
            for item in content:
                if item.get("type") == "text":
                    return item.get("text", "")

            return None

        except Exception as e:
            logger.error(f"Error reading file from local sandbox: {e}")
            return None

    async def write_file(
        self,
        sandbox_id: str,
        file_path: str,
        content: str,
    ) -> bool:
        """Write a file to local sandbox."""
        conn = self._connections.get(sandbox_id)
        if not conn or not conn.client:
            return False

        try:
            await conn.client.call_tool(
                "write",
                {
                    "file_path": file_path,
                    "content": content,
                },
            )
            conn.last_activity_at = datetime.now(UTC)
            return True

        except Exception as e:
            logger.error(f"Error writing file to local sandbox: {e}")
            return False

    # --- Local Sandbox Specific Methods ---

    def get_connection(self, sandbox_id: str) -> LocalSandboxConnection | None:
        """Get a local sandbox connection by ID."""
        return self._connections.get(sandbox_id)

    def get_connection_by_project(self, project_id: str) -> LocalSandboxConnection | None:
        """Get a local sandbox connection by project ID."""
        for conn in self._connections.values():
            if conn.project_id == project_id:
                return conn
        return None

    def is_connected(self, sandbox_id: str) -> bool:
        """Check if a local sandbox is connected."""
        conn = self._connections.get(sandbox_id)
        return conn is not None and conn.status == SandboxStatus.RUNNING

    async def reconnect(self, sandbox_id: str) -> bool:
        """Attempt to reconnect to a disconnected local sandbox."""
        conn = self._connections.get(sandbox_id)
        if not conn:
            return False

        if conn.status == SandboxStatus.RUNNING:
            return True  # Already connected

        try:
            # Disconnect old client to avoid resource leak
            if conn.client:
                with contextlib.suppress(Exception):
                    await conn.client.disconnect()
                conn.client = None

            # Create new client
            client = WebSocketMCPClient(conn.tunnel_url)
            await asyncio.wait_for(
                client.connect(),
                timeout=self._connection_timeout,
            )
            await client.initialize()

            conn.client = client
            conn.status = SandboxStatus.RUNNING
            conn.error_message = None
            conn.last_activity_at = datetime.now(UTC)

            logger.info(f"Reconnected to local sandbox {sandbox_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to reconnect to local sandbox: {e}")
            conn.error_message = f"Reconnection failed: {e}"
            return False
