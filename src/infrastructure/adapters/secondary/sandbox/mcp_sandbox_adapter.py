"""MCP Sandbox Adapter - Docker sandbox with MCP WebSocket server.

This adapter creates Docker containers running the sandbox-mcp-server,
enabling file system operations via the MCP protocol over WebSocket.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Callable, cast

import docker
from docker.errors import ImageNotFound, NotFound

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

import contextlib

from src.domain.ports.services.sandbox_port import (
    CodeExecutionRequest,
    CodeExecutionResult,
    SandboxConfig,
    SandboxConnectionError,
    SandboxInstance,
    SandboxNotFoundError,
    SandboxPort,
    SandboxResourceError,
    SandboxStatus,
)
from src.infrastructure.adapters.secondary.sandbox.constants import (
    DEFAULT_SANDBOX_IMAGE,
    DESKTOP_PORT,
    MCP_WEBSOCKET_PORT,
    TERMINAL_PORT,
)
from src.infrastructure.adapters.secondary.sandbox.url_service import (
    SandboxInstanceInfo,
    SandboxUrlService,
)
from src.infrastructure.mcp.clients.websocket_client import MCPWebSocketClient

logger = logging.getLogger(__name__)


@dataclass
class MCPSandboxInstance(SandboxInstance):
    """Extended sandbox instance with MCP client and service ports."""

    mcp_client: MCPWebSocketClient | None = None
    websocket_url: str | None = None
    # Service ports on host
    mcp_port: int | None = None
    desktop_port: int | None = None
    terminal_port: int | None = None
    # Service URLs
    desktop_url: str | None = None
    terminal_url: str | None = None
    # Labels for identification
    labels: dict[str, str] = field(default_factory=dict)

    @property
    def project_id(self) -> str | None:
        """Get project ID from labels."""
        return self.labels.get("memstack.project_id") or self.labels.get("memstack.project.id")


class MCPSandboxAdapter(SandboxPort):
    """
    MCP-enabled Docker sandbox adapter.

    Creates Docker containers running sandbox-mcp-server, which provides
    file system operations (read, write, edit, glob, grep, bash) via
    MCP protocol over WebSocket.

    This enables remote file system operations in isolated sandbox
    environments with full MCP tool support.

    Usage:
        adapter = MCPSandboxAdapter()

        # Create sandbox
        sandbox = await adapter.create_sandbox("/path/to/project")

        # Connect MCP client
        await adapter.connect_mcp(sandbox.id)

        # Call MCP tools
        result = await adapter.call_tool(
            sandbox.id,
            "read",
            {"file_path": "src/main.py"}
        )

        # Terminate when done
        await adapter.terminate_sandbox(sandbox.id)
    """

    def __init__(
        self,
        mcp_image: str = DEFAULT_SANDBOX_IMAGE,
        default_timeout: int = 60,
        default_memory_limit: str = "2g",
        default_cpu_limit: str = "2",
        host_port_start: int = 18765,
        desktop_port_start: int = 16080,
        terminal_port_start: int = 17681,
        max_concurrent_sandboxes: int = 10,
        max_memory_mb: int = 16384,  # 16GB default
        max_cpu_cores: int = 16,
        workspace_base: str = "/workspace",
    ) -> None:
        """
        Initialize MCP sandbox adapter.

        Args:
            mcp_image: Docker image for sandbox MCP server
            default_timeout: Default execution timeout in seconds
            default_memory_limit: Default memory limit
            default_cpu_limit: Default CPU limit
            host_port_start: Starting port for host port mapping
            desktop_port_start: Starting port for desktop (noVNC) service
            terminal_port_start: Starting port for terminal (ttyd) service
            max_concurrent_sandboxes: Maximum number of concurrent sandboxes
            max_memory_mb: Maximum total memory allocation across all sandboxes
            max_cpu_cores: Maximum total CPU cores across all sandboxes
            workspace_base: Base directory for sandbox workspaces (e.g., /tmp/memstack-sandbox)
        """
        self._mcp_image = mcp_image
        self._default_timeout = default_timeout
        self._default_memory_limit = default_memory_limit
        self._default_cpu_limit = default_cpu_limit
        self._host_port_start = host_port_start
        self._desktop_port_start = desktop_port_start
        self._terminal_port_start = terminal_port_start
        self._workspace_base = workspace_base

        # Resource limits
        self._max_concurrent_sandboxes = max_concurrent_sandboxes
        self._max_memory_mb = max_memory_mb
        self._max_cpu_cores = max_cpu_cores

        # Fine-grained locks for improved concurrency
        # Lock for port allocation operations (port counter, used_ports set)
        self._port_allocation_lock = asyncio.Lock()
        # Lock for instance access (_active_sandboxes dict operations)
        # Using asyncio.Lock - callers should not re-acquire in same task
        self._instance_lock = asyncio.Lock()
        # Lock for cleanup operations (prevent double cleanup)
        self._cleanup_lock = asyncio.Lock()

        # Legacy lock - kept for backward compatibility, maps to instance_lock
        self._lock = self._instance_lock

        # Track active sandboxes and port allocation
        self._active_sandboxes: dict[str, MCPSandboxInstance] = {}
        self._port_counter = 0
        self._desktop_port_counter = 0
        self._terminal_port_counter = 0
        self._used_ports: set[int] = set()

        # Pending queue for sandbox creation requests
        self._pending_queue: list[dict[str, Any]] = []

        # Track cleanup state to prevent double cleanup
        self._cleanup_in_progress: set[str] = set()

        # Track rebuild timestamps using TTL cache to prevent memory leaks
        # Old entries auto-expire after rebuild_ttl_seconds
        from src.infrastructure.adapters.secondary.sandbox.health_monitor import TTLCache

        self._rebuild_cooldown_seconds = 5.0  # Minimum seconds between rebuilds
        self._rebuild_ttl_seconds = 300.0  # Entries expire after 5 minutes
        self._last_rebuild_at: TTLCache = TTLCache(
            default_ttl_seconds=self._rebuild_ttl_seconds,
            max_size=1000,
        )

        # Cache health check results to avoid Docker API call on every call_tool.
        # If a sandbox was checked healthy within this TTL, skip the full health check.
        self._health_check_ttl_seconds = 30.0
        self._last_healthy_at: TTLCache = TTLCache(
            default_ttl_seconds=self._health_check_ttl_seconds,
            max_size=1000,
        )

        # Periodic cleanup task management
        self._cleanup_task: asyncio.Task[None] | None = None
        self._cleanup_interval_seconds = 300.0  # Default: 5 minutes

        # Cleanup statistics
        self._cleanup_stats: dict[str, int | str | None] = {
            "total_cleanups": 0,
            "containers_removed": 0,
            "last_cleanup_at": None,
            "errors": 0,
        }

        # MCP Server health check task management
        self._health_check_task: asyncio.Task[None] | None = None
        self._health_check_interval_seconds = 60.0  # Default: 1 minute

        # Health check statistics
        self._health_check_stats: dict[str, int | str | None] = {
            "total_checks": 0,
            "restarts_triggered": 0,
            "last_check_at": None,
            "errors": 0,
        }

        # MCP server configs for restart (key: (sandbox_id, server_name))
        self._mcp_server_configs: dict[tuple[str, str], dict[str, Any]] = {}

        # URL service for building service URLs
        self._url_service = SandboxUrlService(default_host="localhost", api_base="/api/v1")

        # Initialize Docker client
        try:
            self._docker = docker.from_env()
            logger.info("MCPSandboxAdapter initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Docker client: {e}")
            raise SandboxConnectionError(
                message=f"Failed to connect to Docker: {e}",
                operation="init",
            ) from e

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available on the host.

        Performs two checks:
        1. Checks if port is already tracked as in use
        2. Attempts to bind to the port to verify it's free

        Note: Docker container port check is intentionally omitted here
        because it requires a blocking API call. In-memory tracking via
        _used_ports is sufficient when combined with socket bind check.

        Args:
            port: The port number to check

        Returns:
            True if port is available, False otherwise
        """
        # Check if port is in our tracking set
        if port in self._used_ports:
            return False

        # Try to bind to the port to verify it's free
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(("0.0.0.0", port))
                return True
        except OSError:
            return False

    def _get_next_port_unsafe(self) -> int:
        """Get next available host port for MCP (must be called with lock held)."""
        for _ in range(1000):
            port = self._host_port_start + self._port_counter
            self._port_counter = (self._port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for MCP")

    def _get_next_desktop_port_unsafe(self) -> int:
        """Get next available host port for desktop (noVNC) (must be called with lock held)."""
        for _ in range(1000):
            port = self._desktop_port_start + self._desktop_port_counter
            self._desktop_port_counter = (self._desktop_port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for desktop")

    def _get_next_terminal_port_unsafe(self) -> int:
        """Get next available host port for terminal (ttyd) (must be called with lock held)."""
        for _ in range(1000):
            port = self._terminal_port_start + self._terminal_port_counter
            self._terminal_port_counter = (self._terminal_port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for terminal")

    def _release_ports_unsafe(self, ports: list[int]) -> None:
        """Release ports when sandbox is terminated (must be called with lock held)."""
        for port in ports:
            self._used_ports.discard(port)

    def _extract_ports_from_labels(
        self,
        labels: dict[str, str],
    ) -> tuple[int | None, int | None, int | None]:
        """Extract MCP, desktop, and terminal ports from container labels."""
        mcp_port_str = labels.get("memstack.sandbox.mcp_port", "")
        desktop_port_str = labels.get("memstack.sandbox.desktop_port", "")
        terminal_port_str = labels.get("memstack.sandbox.terminal_port", "")
        mcp_port = int(mcp_port_str) if mcp_port_str else None
        desktop_port = int(desktop_port_str) if desktop_port_str else None
        terminal_port = int(terminal_port_str) if terminal_port_str else None
        return mcp_port, desktop_port, terminal_port

    @staticmethod
    def _extract_project_path_from_mounts(container: Any) -> str:
        """Extract project path from container volume mounts."""
        mounts = container.attrs.get("Mounts", [])
        for mount in mounts:
            if mount.get("Destination") == "/workspace":
                return cast(str, mount.get("Source", ""))
        return ""

    def _build_urls_from_ports(
        self,
        sandbox_id: str,
        mcp_port: int | None,
        desktop_port: int | None,
        terminal_port: int | None,
    ) -> tuple[str | None, str | None, str | None]:
        """Build websocket, desktop, and terminal URLs from port information."""
        if not mcp_port:
            return None, None, None
        instance_info = SandboxInstanceInfo(
            mcp_port=mcp_port,
            desktop_port=desktop_port or 0,
            terminal_port=terminal_port or 0,
            sandbox_id=sandbox_id,
            host="localhost",
        )
        urls = self._url_service.build_all_urls(instance_info)
        websocket_url = urls.mcp_url
        desktop_url = urls.desktop_url if desktop_port else None
        terminal_url = urls.terminal_url if terminal_port else None
        return websocket_url, desktop_url, terminal_url

    def _build_instance_from_container(
        self,
        sandbox_id: str,
        labels: dict[str, str],
        project_path: str,
        mcp_port: int | None,
        desktop_port: int | None,
        terminal_port: int | None,
    ) -> MCPSandboxInstance:
        """Build an MCPSandboxInstance from container metadata."""
        websocket_url, desktop_url, terminal_url = self._build_urls_from_ports(
            sandbox_id,
            mcp_port,
            desktop_port,
            terminal_port,
        )
        now = datetime.now()
        return MCPSandboxInstance(
            id=sandbox_id,
            status=SandboxStatus.RUNNING,
            config=SandboxConfig(image=self._mcp_image),
            project_path=project_path,
            endpoint=websocket_url,
            created_at=now,
            last_activity_at=now,
            websocket_url=websocket_url,
            mcp_client=None,
            mcp_port=mcp_port,
            desktop_port=desktop_port,
            terminal_port=terminal_port,
            desktop_url=desktop_url,
            terminal_url=terminal_url,
            labels=labels,
        )

    def _track_ports(self, *ports: int | None) -> None:
        """Add non-None ports to the used ports set (must hold port_allocation_lock)."""
        for p in ports:
            if p is not None:
                self._used_ports.add(p)

    def _get_instance_ports(self, instance: MCPSandboxInstance) -> list[int]:
        """Get list of non-None ports from an instance."""
        return [
            p
            for p in [instance.mcp_port, instance.desktop_port, instance.terminal_port]
            if p is not None
        ]

    async def _ensure_mcp_connected(
        self,
        sandbox_id: str,
        instance: MCPSandboxInstance,
        timeout: float = 15.0,
    ) -> bool:
        """Ensure MCP client is connected for the instance. Returns True if connected."""
        if instance.mcp_client and instance.mcp_client.is_connected:
            return True
        try:
            return await self.connect_mcp(sandbox_id, timeout=timeout)
        except Exception as e:
            logger.warning(
                "MCP client connect error for %s: %s",
                sandbox_id,
                e,
            )
            return False

    async def _get_connected_mcp_client(
        self,
        sandbox_id: str,
        timeout: float = 15.0,
    ) -> Any | None:
        """Get a connected MCP client for the sandbox, or None if unavailable.

        Resolves the sandbox instance, ensures MCP is connected, and returns the
        client object. Returns None if the sandbox doesn't exist or connection fails.
        """
        instance = await self.get_sandbox(sandbox_id)
        if not instance:
            return None
        if not await self._ensure_mcp_connected(sandbox_id, instance, timeout=timeout):
            return None
        return instance.mcp_client

    async def _safe_stop_and_remove_container(
        self,
        container: Any,
        container_name: str,
        stop_timeout: int = 5,
        overall_timeout: float = 10.0,
    ) -> bool:
        """Stop and remove a container safely. Returns True if successful."""
        loop = asyncio.get_event_loop()
        try:
            if container.status == "running":
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            cast(Callable[[], None], lambda c=container: c.stop(timeout=stop_timeout)),
                        ),
                        timeout=overall_timeout,
                    )
                except TimeoutError:
                    logger.warning(f"Stop timed out for container {container_name}, forcing kill")
                    await loop.run_in_executor(None, container.kill)
            await loop.run_in_executor(None, cast(Callable[[], None], lambda c=container: c.remove(force=True)))
            return True
        except Exception as e:
            logger.warning(f"Failed to stop/remove container {container_name}: {e}")
            return False

    async def create_sandbox(
        self,
        project_path: str,
        config: SandboxConfig | None = None,
        project_id: str | None = None,
        tenant_id: str | None = None,
        sandbox_id: str | None = None,
    ) -> MCPSandboxInstance:
        """
        Create a new MCP sandbox container.

        Args:
            project_path: Path to mount as workspace
            config: Sandbox configuration
            project_id: Optional project ID for labeling and identification
            tenant_id: Optional tenant ID for labeling and identification
            sandbox_id: Optional sandbox ID to reuse (for recreating with same ID)

        Returns:
            MCPSandboxInstance with MCP endpoint
        """
        config = config or SandboxConfig(image=self._mcp_image)

        # Enforce resource limits
        if not self.can_create_sandbox():
            raise SandboxResourceError(
                f"Cannot create sandbox: concurrent limit reached "
                f"({self.active_count}/{self._max_concurrent_sandboxes})"
            )

        # Use provided sandbox_id or generate a new one
        sandbox_id = sandbox_id or f"mcp-sandbox-{uuid.uuid4().hex[:12]}"

        # Note: We don't cleanup project containers here anymore.
        # The get_or_create_sandbox method already checks for existing sandboxes
        # before calling create_sandbox. Cleanup was causing issues by removing
        # valid running containers that should be reused.

        # Allocate ports for all services with lock protection
        async with self._port_allocation_lock:
            host_mcp_port = self._get_next_port_unsafe()
            host_desktop_port = self._get_next_desktop_port_unsafe()
            host_terminal_port = self._get_next_terminal_port_unsafe()

        try:
            # Container configuration with all service ports
            container_config = {
                "image": self._mcp_image,
                "name": sandbox_id,
                "hostname": sandbox_id,  # Set hostname to sandbox_id for VNC hostname resolution
                "detach": True,
                # Auto-restart policy for container-level recovery
                # Docker will restart the container if it exits with non-zero code
                "restart_policy": {"Name": "on-failure", "MaximumRetryCount": 3},
                # Add extra hosts to resolve the container hostname (required for VNC)
                "extra_hosts": {sandbox_id: "127.0.0.1"},
                "ports": {
                    f"{MCP_WEBSOCKET_PORT}/tcp": host_mcp_port,
                    f"{DESKTOP_PORT}/tcp": host_desktop_port,
                    f"{TERMINAL_PORT}/tcp": host_terminal_port,
                },
                "environment": {
                    "SANDBOX_ID": sandbox_id,
                    "MCP_HOST": "0.0.0.0",
                    "MCP_PORT": str(MCP_WEBSOCKET_PORT),
                    "MCP_WORKSPACE": "/workspace",
                    "DESKTOP_PORT": str(DESKTOP_PORT),
                    "TERMINAL_PORT": str(TERMINAL_PORT),
                    **config.environment,
                },
                "mem_limit": config.memory_limit or self._default_memory_limit,
                "cpu_quota": int(float(config.cpu_limit or self._default_cpu_limit) * 100000),
                # Labels for identification
                "labels": {
                    "memstack.sandbox": "true",
                    "memstack.sandbox.id": sandbox_id,
                    "memstack.sandbox.mcp_port": str(host_mcp_port),
                    "memstack.sandbox.desktop_port": str(host_desktop_port),
                    "memstack.sandbox.terminal_port": str(host_terminal_port),
                    **(
                        {
                            "memstack.project_id": project_id,
                        }
                        if project_id
                        else {}
                    ),
                    **(
                        {
                            "memstack.tenant_id": tenant_id,
                        }
                        if tenant_id
                        else {}
                    ),
                },
            }

            # Volume mounts
            volumes = {}
            if project_path:
                volumes[project_path] = {"bind": "/workspace", "mode": "rw"}
            if volumes:
                container_config["volumes"] = volumes

            # Network mode - need network for WebSocket
            # Don't use "none" as we need to connect via host port
            if config.network_isolated:
                # Create isolated network for sandbox
                container_config["network_mode"] = "bridge"

            # Run in thread pool
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self._docker.containers.run(**container_config),
            )

            # Wait for container to be ready
            await asyncio.sleep(1)

            # Build service URLs using SandboxUrlService
            instance_info = SandboxInstanceInfo(
                mcp_port=host_mcp_port,
                desktop_port=host_desktop_port,
                terminal_port=host_terminal_port,
                sandbox_id=sandbox_id,
                host="localhost",
            )
            urls = self._url_service.build_all_urls(instance_info)

            websocket_url = urls.mcp_url
            desktop_url = urls.desktop_url
            terminal_url = urls.terminal_url

            # Build labels dict for instance
            instance_labels = {
                "memstack.sandbox": "true",
                "memstack.sandbox.id": sandbox_id,
                "memstack.sandbox.mcp_port": str(host_mcp_port),
                "memstack.sandbox.desktop_port": str(host_desktop_port),
                "memstack.sandbox.terminal_port": str(host_terminal_port),
            }
            if project_id:
                instance_labels["memstack.project_id"] = project_id
            if tenant_id:
                instance_labels["memstack.tenant_id"] = tenant_id

            # Create instance record with port information
            now = datetime.now()
            instance = MCPSandboxInstance(
                id=sandbox_id,
                status=SandboxStatus.RUNNING,
                config=config,
                project_path=project_path,
                endpoint=websocket_url,
                created_at=now,
                last_activity_at=now,  # Initialize activity time
                websocket_url=websocket_url,
                mcp_client=None,
                mcp_port=host_mcp_port,
                desktop_port=host_desktop_port,
                terminal_port=host_terminal_port,
                desktop_url=desktop_url,
                terminal_url=terminal_url,
                labels=instance_labels,
            )

            async with self._instance_lock:
                self._active_sandboxes[sandbox_id] = instance
            logger.info(
                f"Created MCP sandbox: {sandbox_id} "
                f"(MCP: {host_mcp_port}, Desktop: {host_desktop_port}, Terminal: {host_terminal_port})"
            )

            return instance

        except ImageNotFound:
            # Release allocated ports on failure
            async with self._port_allocation_lock:
                self._release_ports_unsafe([host_mcp_port, host_desktop_port, host_terminal_port])
            logger.error(f"MCP sandbox image not found: {self._mcp_image}")
            raise SandboxConnectionError(
                message=f"Docker image not found: {self._mcp_image}. "
                f"Build with: cd sandbox-mcp-server && docker build -t {self._mcp_image} .",
                sandbox_id=sandbox_id,
                operation="create",
            ) from None
        except Exception as e:
            # Release allocated ports on failure
            async with self._port_allocation_lock:
                self._release_ports_unsafe([host_mcp_port, host_desktop_port, host_terminal_port])
            logger.error(f"Failed to create MCP sandbox: {e}")
            raise SandboxConnectionError(
                message=f"Failed to create sandbox: {e}",
                sandbox_id=sandbox_id,
                operation="create",
            ) from e

    async def _verify_container_running(self, sandbox_id: str) -> bool:
        """Check if a Docker container exists and is running."""
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None, lambda: self._docker.containers.get(sandbox_id)
            )
            if container.status != "running":
                logger.warning(
                    f"Sandbox {sandbox_id} container not running (status={container.status}), "
                    "connection will fail. Caller should trigger rebuild first."
                )
                return False
        except Exception:
            logger.warning(f"Sandbox {sandbox_id} container not found")
            return False
        return True

    async def connect_mcp(
        self,
        sandbox_id: str,
        timeout: float = 30.0,
        max_retries: int = 3,
        backoff_factor: float = 1.0,
    ) -> bool:
        """
        Connect MCP client to sandbox with retry and auto-rebuild.

        If the container is dead or unhealthy, attempts to rebuild it
        before retrying the connection.

        Args:
            sandbox_id: Sandbox identifier
            timeout: Connection timeout in seconds
            max_retries: Maximum number of retry attempts
            backoff_factor: Backoff multiplier between retries

        Returns:
            True if connected successfully
        """
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {sandbox_id}",
                sandbox_id=sandbox_id,
                operation="connect_mcp",
            )

        if instance.mcp_client and instance.mcp_client.is_connected:
            logger.debug(f"MCP client already connected: {sandbox_id}")
            return True

        # NOTE: Health check and rebuild should be done BEFORE calling connect_mcp.
        # This method only attempts connection; rebuild logic is in:
        # - _ensure_sandbox_healthy (called by call_tool)
        # - _rebuild_sandbox (for explicit rebuild requests)
        if not await self._verify_container_running(sandbox_id):
            return False

        # Refresh instance reference
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            logger.error(f"Sandbox {sandbox_id} not found")
            return False

        # Create MCP client (heartbeat=None to avoid PONG timeout killing long tool calls)
        client = MCPWebSocketClient(
            url=instance.websocket_url or "",
            timeout=timeout,
            heartbeat_interval=None,
        )

        # Connect with exponential backoff retry
        for attempt in range(max_retries):
            try:
                connected = await client.connect(timeout=timeout)
                if connected:
                    instance.mcp_client = client
                    logger.info(f"MCP client connected: {sandbox_id}")
                    return True
            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = backoff_factor * (2**attempt)
                    logger.warning(
                        f"MCP connection attempt {attempt + 1}/{max_retries} "
                        f"failed for {sandbox_id}: {e}. Retrying in {wait_time}s..."
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        f"Failed to connect MCP client after {max_retries} attempts: {sandbox_id}"
                    )
                    return False

        return False

    async def disconnect_mcp(self, sandbox_id: str) -> None:
        """Disconnect MCP client from sandbox."""
        instance = self._active_sandboxes.get(sandbox_id)
        if instance and instance.mcp_client:
            await instance.mcp_client.disconnect()
            instance.mcp_client = None
            logger.info(f"MCP client disconnected: {sandbox_id}")

    async def list_tools(self, sandbox_id: str) -> list[dict[str, Any]]:
        """
        List available MCP tools.

        Args:
            sandbox_id: Sandbox identifier

        Returns:
            List of tool definitions
        """
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {sandbox_id}",
                sandbox_id=sandbox_id,
                operation="list_tools",
            )

        if not instance.mcp_client or not instance.mcp_client.is_connected:
            await self.connect_mcp(sandbox_id)

        if not instance.mcp_client:
            return []

        tools = instance.mcp_client.get_cached_tools()
        result = []
        for t in tools:
            tool_info = {
                "name": t.name,
                "description": t.description,
                "input_schema": t.inputSchema,
            }
            if t.meta:
                tool_info["_meta"] = t.meta
            result.append(tool_info)
        return result

    async def read_resource(self, sandbox_id: str, uri: str) -> str | None:
        """Read a resource from a sandbox MCP server via resources/read.

        Args:
            sandbox_id: Sandbox identifier.
            uri: Resource URI (e.g., ui://server/app.html).

        Returns:
            HTML content string, or None if unavailable.
        """
        # Use get_sandbox() which auto-recovers from Docker if not in memory
        instance = await self.get_sandbox(sandbox_id)
        if not instance:
            logger.warning("read_resource: sandbox %s not found", sandbox_id)
            return None

        # Auto-connect MCP client if needed
        if not await self._ensure_mcp_connected(sandbox_id, instance, timeout=15.0):
            logger.warning("read_resource: MCP client not connected for %s", sandbox_id)
            return None

        try:
            result = await instance.mcp_client.read_resource(uri)
            if not result:
                return None

            contents = result.get("contents", [])
            for item in contents:
                if isinstance(item, dict):
                    text = item.get("text", "")
                    if text:
                        return cast(str | None, text)
            return None
        except Exception as e:
            logger.warning("read_resource error for %s: %s", uri, e)
            return None

    async def list_resources(self, sandbox_id: str) -> list[Any]:
        """List resources from sandbox MCP servers via resources/list.
        List of resource descriptors, or empty list.
        """
        client = await self._get_connected_mcp_client(sandbox_id, timeout=15.0)
        if not client:
            return []

        try:
            result = await client.list_resources()
            return result.get("resources", []) if result else []
        except Exception as e:
            logger.warning("list_resources error for sandbox %s: %s", sandbox_id, e)
            return []

    # === SandboxPort interface implementation ===

    async def _recover_sandbox_from_docker(
        self,
        sandbox_id: str,
    ) -> MCPSandboxInstance | None:
        """Recover a sandbox from Docker when not in memory (e.g. after API restart)."""
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            # Container exists but not running
            if container.status != "running":
                return None

            logger.info(f"Recovering sandbox {sandbox_id} from Docker (API restart)")

            labels = container.labels or {}
            mcp_port, desktop_port, terminal_port = self._extract_ports_from_labels(labels)
            project_path = self._extract_project_path_from_mounts(container)

            instance = self._build_instance_from_container(
                sandbox_id,
                labels,
                project_path,
                mcp_port,
                desktop_port,
                terminal_port,
            )

            # Use separate locks for instance and port tracking
            async with self._instance_lock:
                self._active_sandboxes[sandbox_id] = instance
            async with self._port_allocation_lock:
                self._track_ports(mcp_port, desktop_port, terminal_port)

            logger.info(
                f"Successfully recovered sandbox {sandbox_id} "
                f"(MCP: {mcp_port}, Desktop: {desktop_port}, Terminal: {terminal_port})"
            )
            return instance

        except NotFound:
            logger.debug(f"Sandbox {sandbox_id} not found in Docker")
            return None
        except Exception as e:
            logger.warning(
                f"Error recovering sandbox {sandbox_id} from Docker: {type(e).__name__}: {e}"
            )
            return None

    async def get_sandbox(self, sandbox_id: str) -> MCPSandboxInstance | None:
        """Get sandbox instance by ID.

        If the sandbox is not in memory but exists in Docker, attempt to recover it.
        This handles API restarts where the in-memory cache is lost.
        """
        # Fast path: sandbox is already in memory
        if sandbox_id in self._active_sandboxes:
            instance = self._active_sandboxes[sandbox_id]

            # Update status from Docker
            try:
                loop = asyncio.get_event_loop()
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )

                status_map = {
                    "running": SandboxStatus.RUNNING,
                    "exited": SandboxStatus.STOPPED,
                    "created": SandboxStatus.CREATING,
                }
                instance.status = status_map.get(container.status, SandboxStatus.ERROR)

            except NotFound:
                del self._active_sandboxes[sandbox_id]
                return None
            except Exception as e:
                logger.warning(f"Error getting sandbox status: {e}")

            return instance

        # Recovery path: sandbox not in memory, check Docker
        return await self._recover_sandbox_from_docker(sandbox_id)

    async def _cleanup_instance_tracking(self, sandbox_id: str) -> None:
        """Remove sandbox from active tracking and release its ports.

        Handles instance_lock and port_allocation_lock internally.
        Safe to call even if sandbox is not tracked.
        """
        ports_to_release: list[int] = []
        async with self._instance_lock:
            instance = self._active_sandboxes.get(sandbox_id)
            if instance:
                ports_to_release = [
                    instance.mcp_port,
                    instance.desktop_port,
                    instance.terminal_port,
                ]
                ports_to_release = [p for p in ports_to_release if p is not None]
                instance.status = SandboxStatus.TERMINATED
                instance.terminated_at = datetime.now()
                del self._active_sandboxes[sandbox_id]
        async with self._port_allocation_lock:
            self._release_ports_unsafe(ports_to_release)
        # Invalidate health check cache
        await self._last_healthy_at.delete(sandbox_id)

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Terminate a sandbox container with proper cleanup and locking."""
        # Prevent double cleanup with cleanup lock
        async with self._cleanup_lock:
            if sandbox_id in self._cleanup_in_progress:
                logger.warning(f"Cleanup already in progress for sandbox: {sandbox_id}")
                return False
            self._cleanup_in_progress.add(sandbox_id)

        try:
            # Disconnect MCP client first
            await self.disconnect_mcp(sandbox_id)

            # Stop and remove container with timeout protection
            loop = asyncio.get_event_loop()
            try:
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )
                container_name = container.name or sandbox_id
                await self._safe_stop_and_remove_container(
                    container, container_name, stop_timeout=5, overall_timeout=15.0
                )
            except NotFound:
                logger.warning(f"Container not found for termination: {sandbox_id}")

            # Update instance tracking and release ports
            await self._cleanup_instance_tracking(sandbox_id)

            logger.info(f"Terminated MCP sandbox: {sandbox_id}")
            return True

        except Exception as e:
            logger.error(f"Error terminating sandbox {sandbox_id}: {e}")
            # Ensure cleanup even on error - release ports to prevent leak
            await self._cleanup_instance_tracking(sandbox_id)
            return False
        finally:
            # Always remove from cleanup tracking
            async with self._cleanup_lock:
                self._cleanup_in_progress.discard(sandbox_id)

    async def container_exists(self, sandbox_id: str) -> bool:
        """Check if a Docker container actually exists and is running.

        This is a direct Docker API check, bypassing internal caches.
        Used to detect containers that were externally killed or deleted.

        Args:
            sandbox_id: The container ID or name to check

        Returns:
            True if container exists and is running, False otherwise
        """
        if not sandbox_id:
            return False

        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )
            # Container exists, check if running
            return cast(bool, container.status == "running")
        except NotFound:
            # Container doesn't exist
            return False
        except Exception as e:
            logger.warning(f"Error checking container existence for {sandbox_id}: {e}")
            return False

    async def get_sandbox_id_by_project(self, project_id: str) -> str | None:
        """Get sandbox ID for a specific project.

        Searches active sandboxes for one associated with the given project ID.

        Args:
            project_id: The project ID to look up

        Returns:
            The sandbox ID if found, None otherwise
        """
        if not project_id:
            return None

        async with self._instance_lock:
            for sandbox_id, instance in self._active_sandboxes.items():
                if instance.labels.get("memstack.project_id") == project_id:
                    return sandbox_id

        # Also check Docker containers in case instance isn't in memory
        try:
            containers = self._docker.containers.list(
                filters={
                    "label": [
                        "memstack.sandbox=true",
                        f"memstack.project_id={project_id}",
                    ]
                }
            )
            if containers:
                # Get sandbox ID from container labels
                labels = containers[0].labels
                return cast(str | None, labels.get("memstack.sandbox.id"))
        except Exception as e:
            logger.warning(f"Error looking up sandbox by project: {e}")

        return None

    def _find_containers_by_mount_or_name(
        self,
        containers: list[Any],
        project_id: str,
    ) -> set[str]:
        """Find container IDs matching a project by mount path or container name.

        Args:
            containers: List of Docker container objects to search.
            project_id: Project ID to match against.

        Returns:
            Set of matching container IDs.
        """
        matched: set[str] = set()
        mount_pattern = f"memstack_{project_id}"
        for container in containers:
            try:
                # Check container mounts
                mounts = container.attrs.get("Mounts", [])
                for mount in mounts:
                    source = mount.get("Source", "")
                    if mount_pattern in source:
                        matched.add(container.id)
                        break

                # Also check container name
                container_name = container.name or ""
                if mount_pattern in container_name or project_id in container_name:
                    matched.add(container.id)
            except Exception as e:
                logger.warning(f"Error checking container {container.id}: {e}")
        return matched

    async def _terminate_and_cleanup_container(
        self,
        container_id: str,
        loop: asyncio.AbstractEventLoop,
        project_id: str,
    ) -> bool:
        """Stop, remove a single container and clean up its internal tracking.
        Args:
            container_id: Docker container ID to terminate.
            loop: Event loop for executor calls.
            project_id: Project ID for logging.
            True if container was successfully cleaned up.
        """
        try:
            container = self._docker.containers.get(container_id)
            container_name = container.name or container_id
            await self._safe_stop_and_remove_container(
                container, container_name, stop_timeout=5, overall_timeout=10.0
            )
            await self._cleanup_instance_tracking(container_name)
            logger.info(f"Cleaned up container {container_name} for project {project_id}")
            return True
        except Exception as e:
            logger.warning(f"Failed to cleanup container {container_id}: {e}")
            return False

    async def cleanup_project_containers(self, project_id: str) -> int:
        """Clean up all existing containers for a specific project.

        This ensures only one container exists per project by removing any
        orphan containers before creating a new one.

        ENHANCED: Also cleans up containers that match by mount path pattern,
        not just by label. This handles cases where containers were created
        by old APIs without proper project_id labels.

        Args:
            project_id: The project ID to clean up containers for

        Returns:
            Number of containers terminated
        """
        if not project_id:
            return 0

        terminated_count = 0
        containers_to_cleanup = set()

        try:
            loop = asyncio.get_event_loop()

            # Method 1: Find containers by project_id label (preferred)
            labeled_containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,  # Include stopped containers
                    filters={
                        "label": [
                            "memstack.sandbox=true",
                            f"memstack.project_id={project_id}",
                        ]
                    },
                ),
            )
            for c in labeled_containers:
                containers_to_cleanup.add(c.id)

            # Method 2: Find containers by mount path pattern (fallback for old containers)
            # This catches containers created without proper labels
            all_sandbox_containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,
                    filters={"label": "memstack.sandbox=true"},
                ),
            )

            containers_to_cleanup.update(
                self._find_containers_by_mount_or_name(all_sandbox_containers, project_id)
            )

            if not containers_to_cleanup:
                return 0

            logger.info(
                f"Found {len(containers_to_cleanup)} container(s) for project {project_id}, cleaning up..."
            )

            # Get container objects and clean up
            for container_id in containers_to_cleanup:
                success = await self._terminate_and_cleanup_container(
                    container_id, loop, project_id
                )
                if success:
                    terminated_count += 1

            return terminated_count

        except Exception as e:
            logger.error(f"Error cleaning up project containers for {project_id}: {e}")
            return terminated_count

    async def execute_code(
        self,
        request: CodeExecutionRequest,
    ) -> CodeExecutionResult:
        """Execute code using MCP bash tool."""
        import time

        start_time = time.time()

        try:
            # Use bash tool for code execution
            if request.language == "python":
                code_escaped = request.code.replace("'", "'\\''")
                command = f"python3 -c '{code_escaped}'"
            else:
                command = request.code

            result = await self.call_tool(
                request.sandbox_id,
                "bash",
                {
                    "command": command,
                    "timeout": request.timeout_seconds or self._default_timeout,
                    "working_dir": request.working_directory,
                },
            )

            execution_time_ms = int((time.time() - start_time) * 1000)

            # Parse result
            content = result.get("content", [])
            output = ""
            if content and len(content) > 0:
                output = content[0].get("text", "")

            return CodeExecutionResult(
                success=not result.get("is_error", False),
                stdout=output if not result.get("is_error") else "",
                stderr=output if result.get("is_error") else "",
                exit_code=0 if not result.get("is_error") else 1,
                execution_time_ms=execution_time_ms,
                output_files=[],
                error=output if result.get("is_error") else None,
            )

        except Exception as e:
            logger.error(f"Code execution error: {e}")
            return CodeExecutionResult(
                success=False,
                stdout="",
                stderr=str(e),
                exit_code=-1,
                execution_time_ms=int((time.time() - start_time) * 1000),
                error=str(e),
            )

    async def stream_execute(
        self,
        request: CodeExecutionRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream code execution output."""
        result = await self.execute_code(request)

        if result.stdout:
            yield {"type": "stdout", "data": result.stdout}
        if result.stderr:
            yield {"type": "stderr", "data": result.stderr}

        yield {
            "type": "status",
            "data": {
                "success": result.success,
                "exit_code": result.exit_code,
                "execution_time_ms": result.execution_time_ms,
            },
        }

    async def list_sandboxes(
        self,
        status: SandboxStatus | None = None,
    ) -> list[MCPSandboxInstance]:
        """List all sandbox instances (thread-safe)."""
        async with self._instance_lock:
            result = []
            for instance in list(self._active_sandboxes.values()):
                if status is None or instance.status == status:
                    result.append(instance)
            return result

    async def sync_sandbox_from_docker(self, sandbox_id: str) -> MCPSandboxInstance | None:
        """
        Sync a specific sandbox from Docker by container name/ID.

        This method is used when a sandbox is not found in _active_sandboxes
        but may have been created/recreated by another process (e.g., API server
        using ProjectSandboxLifecycleService while Agent Worker is running).

        Args:
            sandbox_id: The sandbox ID (container name) to sync

        Returns:
            MCPSandboxInstance if found and synced, None otherwise
        """
        try:
            loop = asyncio.get_event_loop()

            # Try to get the container by name
            try:
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )
            except Exception:
                # Container doesn't exist
                logger.debug(f"Container {sandbox_id} not found in Docker")
                return None

            # Skip non-running containers
            if container.status != "running":
                logger.debug(f"Container {sandbox_id} exists but not running: {container.status}")
                return None

            labels = container.labels or {}

            # Verify it's a memstack sandbox
            if labels.get("memstack.sandbox") != "true":
                logger.debug(f"Container {sandbox_id} is not a memstack sandbox")
                return None

            # Extract port information from labels
            mcp_port_str = labels.get("memstack.sandbox.mcp_port", "")
            desktop_port_str = labels.get("memstack.sandbox.desktop_port", "")
            terminal_port_str = labels.get("memstack.sandbox.terminal_port", "")

            mcp_port = int(mcp_port_str) if mcp_port_str else None
            desktop_port = int(desktop_port_str) if desktop_port_str else None
            terminal_port = int(terminal_port_str) if terminal_port_str else None

            # Get project path from volume mounts
            project_path = ""
            mounts = container.attrs.get("Mounts", [])
            for mount in mounts:
                if mount.get("Destination") == "/workspace":
                    project_path = mount.get("Source", "")
                    break

            # Build URLs if ports are available
            websocket_url = None
            desktop_url = None
            terminal_url = None
            if mcp_port:
                instance_info = SandboxInstanceInfo(
                    mcp_port=mcp_port,
                    desktop_port=desktop_port or 0,
                    terminal_port=terminal_port or 0,
                    sandbox_id=sandbox_id,
                    host="localhost",
                )
                urls = self._url_service.build_all_urls(instance_info)
                websocket_url = urls.mcp_url
                desktop_url = urls.desktop_url if desktop_port else None
                terminal_url = urls.terminal_url if terminal_port else None

            # Create instance record
            now = datetime.now()
            instance = MCPSandboxInstance(
                id=sandbox_id,
                status=SandboxStatus.RUNNING,
                config=SandboxConfig(image=self._mcp_image),
                project_path=project_path,
                endpoint=websocket_url,
                created_at=now,
                last_activity_at=now,
                websocket_url=websocket_url,
                mcp_client=None,  # Will connect on first use
                mcp_port=mcp_port,
                desktop_port=desktop_port,
                terminal_port=terminal_port,
                desktop_url=desktop_url,
                terminal_url=terminal_url,
                labels=labels,
            )

            async with self._instance_lock:
                self._active_sandboxes[sandbox_id] = instance
                # Track used ports
                if mcp_port:
                    self._used_ports.add(mcp_port)
                if desktop_port:
                    self._used_ports.add(desktop_port)
                if terminal_port:
                    self._used_ports.add(terminal_port)

            logger.info(
                f"Synced sandbox {sandbox_id} from Docker "
                f"(project_id={labels.get('memstack.project_id', 'unknown')}, "
                f"mcp_port={mcp_port})"
            )
            return instance

        except Exception as e:
            logger.error(f"Error syncing sandbox {sandbox_id} from Docker: {e}")
            return None

    async def _remove_orphan_sync_container(
        self,
        container: Any,
        loop: asyncio.AbstractEventLoop,
    ) -> bool:
        """Remove an orphan container during sync (no project_id label).

        Returns True if successfully removed.
        """
        logger.warning(
            f"Cleaning up orphan sandbox container {container.name} "
            f"(no project_id label, status={container.status})"
        )
        try:
            await loop.run_in_executor(None, cast(Callable[[], None], lambda c=container: c.remove(force=True)))
            return True
        except Exception as e:
            logger.warning(f"Failed to cleanup orphan container {container.name}: {e}")
            return False

    def _sync_container_to_instance(
        self,
        container: Any,
    ) -> None:
        """Extract metadata from a running container and register it in tracking.

        Must be called while holding _instance_lock.
        """
        labels = container.labels or {}
        sandbox_id = labels.get("memstack.sandbox.id", container.name)

        mcp_port, desktop_port, terminal_port = self._extract_ports_from_labels(labels)
        project_path = self._extract_project_path_from_mounts(container)

        instance = self._build_instance_from_container(
            sandbox_id, labels, project_path, mcp_port, desktop_port, terminal_port
        )
        self._active_sandboxes[sandbox_id] = instance
        self._track_ports(mcp_port, desktop_port, terminal_port)

        logger.info(
            f"Discovered existing sandbox: {sandbox_id} "
            f"(project_id={labels.get('memstack.project_id', 'unknown')})"
        )

    async def sync_from_docker(self) -> int:
        """
        Discover existing sandbox containers from Docker and sync to internal state.

        This method is called on startup to recover existing sandbox containers
        that may have been created before the adapter was (re)initialized.
        It queries Docker for containers with memstack.sandbox labels and
        rebuilds the internal tracking state.

        Returns:
            Number of sandboxes discovered and synced
        """
        try:
            loop = asyncio.get_event_loop()

            # List all containers with memstack.sandbox label
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,
                    filters={"label": "memstack.sandbox=true"},
                ),
            )

            count = 0
            orphans_cleaned = 0
            async with self._instance_lock:
                for container in containers:
                    if container.name in self._active_sandboxes:
                        continue

                    labels = container.labels or {}

                    if not labels.get("memstack.project_id"):
                        if await self._remove_orphan_sync_container(container, loop):
                            orphans_cleaned += 1
                        continue

                    if container.status != "running":
                        continue

                    self._sync_container_to_instance(container)
                    count += 1

            if orphans_cleaned > 0:
                logger.info(
                    f"Cleaned up {orphans_cleaned} orphan sandbox containers (no project_id label)"
                )
            if count > 0:
                logger.info(f"Synced {count} existing sandbox containers from Docker")

            return count

        except Exception as e:
            logger.error(f"Error syncing sandboxes from Docker: {e}")
            return 0

    async def get_output_files(
        self,
        sandbox_id: str,
        output_dir: str = "/output",
    ) -> dict[str, bytes]:
        """Retrieve output files using MCP tools."""
        try:
            # Use glob to list files
            glob_result = await self.call_tool(
                sandbox_id,
                "glob",
                {"pattern": "**/*", "path": output_dir},
            )

            if glob_result.get("is_error"):
                return {}

            # Get file list from result
            content = glob_result.get("content", [])
            if not content:
                return {}

            files_text = content[0].get("text", "")
            file_paths = [f.strip() for f in files_text.split("\n") if f.strip()]

            # Read each file
            files = {}
            for file_path in file_paths:
                read_result = await self.call_tool(
                    sandbox_id,
                    "read",
                    {"file_path": f"{output_dir}/{file_path}"},
                )
                if not read_result.get("is_error"):
                    content = read_result.get("content", [])
                    if content:
                        files[file_path] = content[0].get("text", "").encode("utf-8")

            return files

        except Exception as e:
            logger.error(f"Error getting output files: {e}")
            return {}

    async def cleanup_expired(
        self,
        max_age_seconds: int = 3600,
    ) -> int:
        """Clean up expired sandbox instances (thread-safe)."""
        now = datetime.now()
        expired_ids = []

        # Get expired IDs with lock protection
        async with self._instance_lock:
            for sandbox_id, instance in list(self._active_sandboxes.items()):
                age = (now - instance.created_at).total_seconds()
                if age > max_age_seconds:
                    expired_ids.append(sandbox_id)

        count = 0
        for sandbox_id in expired_ids:
            try:
                if await self.terminate_sandbox(sandbox_id):
                    count += 1
            except Exception as e:
                logger.error(f"Failed to cleanup expired sandbox {sandbox_id}: {e}")

        if count > 0:
            logger.info(f"Cleaned up {count} expired MCP sandboxes")

        return count

    async def get_sandbox_stats(
        self, sandbox_id: str, project_id: str | None = None
    ) -> dict[str, Any]:
        """
        Get container resource usage statistics.

        Args:
            sandbox_id: Sandbox identifier
            project_id: Optional project ID to search by label if sandbox_id not found

        Returns:
            Dict with cpu_percent, memory_usage, memory_limit, etc.
        """
        try:
            loop = asyncio.get_event_loop()
            container = None

            # Try to get container by sandbox_id first
            try:
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )
            except Exception:
                # If not found by ID and project_id is provided, search by label
                if project_id:
                    containers = await loop.run_in_executor(
                        None,
                        lambda: self._docker.containers.list(
                            filters={
                                "label": [
                                    "memstack.sandbox=true",
                                    f"memstack.project_id={project_id}",
                                ],
                                "status": "running",
                            }
                        ),
                    )
                    if containers:
                        container = containers[0]
                        logger.info(f"Found container {container.id} by project_id {project_id}")

            if not container:
                logger.warning(f"Container not found: {sandbox_id}")
                return {}

            stats = container.stats(stream=False)

            # Calculate CPU percentage
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"] - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0

            memory_stats = stats.get("memory_stats", {})

            # Network I/O stats
            networks = stats.get("networks", {})
            network_rx_bytes = 0
            network_tx_bytes = 0
            for interface_stats in networks.values():
                network_rx_bytes += interface_stats.get("rx_bytes", 0)
                network_tx_bytes += interface_stats.get("tx_bytes", 0)

            # Block I/O stats (disk)
            blkio_stats = stats.get("blkio_stats", {})
            disk_read_bytes = 0
            disk_write_bytes = 0
            for entry in blkio_stats.get("io_service_bytes_recursive", []) or []:
                if entry.get("op") == "read":
                    disk_read_bytes += entry.get("value", 0)
                elif entry.get("op") == "write":
                    disk_write_bytes += entry.get("value", 0)

            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_usage": memory_stats.get("usage", 0),
                "memory_limit": memory_stats.get("limit", 1),
                "memory_percent": round(
                    (memory_stats.get("usage", 0) / memory_stats.get("limit", 1)) * 100, 2
                ),
                "network_rx_bytes": network_rx_bytes,
                "network_tx_bytes": network_tx_bytes,
                "disk_read_bytes": disk_read_bytes,
                "disk_write_bytes": disk_write_bytes,
                "pids": stats.get("pids_stats", {}).get("current", 0),
                "status": container.status,
            }

        except Exception as e:
            logger.error(f"Error getting sandbox stats: {e}")
            return {}

    async def health_check(self, sandbox_id: str) -> bool:
        """
        Perform health check on a sandbox.

        Args:
            sandbox_id: Sandbox identifier

        Returns:
            True if healthy
        """
        try:
            # Check if sandbox exists in tracking
            instance = self._active_sandboxes.get(sandbox_id)
            if not instance:
                return False

            # Check container status
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            if container.status != "running":
                logger.warning(f"Sandbox {sandbox_id} container not running: {container.status}")
                return False

            # Check MCP connection
            if not instance.mcp_client or not instance.mcp_client.is_connected:
                # Try to reconnect
                connected = await self.connect_mcp(sandbox_id, timeout=10.0)
                if not connected:
                    logger.warning(f"Sandbox {sandbox_id} MCP not connected")
                    return False

            return True

        except Exception as e:
            logger.error(f"Health check failed for {sandbox_id}: {e}")
            return False

    async def cleanup_orphaned(self) -> int:
        """
        Clean up orphaned sandbox containers not in tracking.

        Returns:
            Number of containers cleaned up
        """
        try:
            loop = asyncio.get_event_loop()
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(filters={"label": "memstack.sandbox=true"}),
            )

            count = 0
            for container in containers:
                if container.name not in self._active_sandboxes:
                    logger.warning(f"Found orphaned sandbox container: {container.name}")
                    try:
                        await loop.run_in_executor(None, cast(Callable[[], None], lambda c=container: c.stop(timeout=5)))
                        await loop.run_in_executor(None, container.remove)
                        count += 1
                    except Exception as e:
                        logger.error(f"Failed to cleanup orphaned container {container.name}: {e}")

            if count > 0:
                logger.info(f"Cleaned up {count} orphaned sandbox containers")

            return count

        except Exception as e:
            logger.error(f"Error cleaning up orphaned containers: {e}")
            return 0

    # === Resource Management Properties ===

    @property
    def max_concurrent(self) -> int:
        """Maximum number of concurrent sandboxes allowed."""
        return self._max_concurrent_sandboxes

    @property
    def max_memory_mb(self) -> int:
        """Maximum total memory in MB across all sandboxes."""
        return self._max_memory_mb

    @property
    def max_cpu_cores(self) -> int:
        """Maximum total CPU cores across all sandboxes."""
        return self._max_cpu_cores

    @property
    def active_count(self) -> int:
        """Current number of active (running) sandboxes."""
        return sum(1 for s in self._active_sandboxes.values() if s.status == SandboxStatus.RUNNING)

    # === Concurrency Control ===

    # Maximum pending queue size to prevent memory issues
    MAX_PENDING_QUEUE_SIZE = 100
    # Maximum age for pending requests in seconds
    MAX_PENDING_REQUEST_AGE = 300  # 5 minutes

    def can_create_sandbox(self) -> bool:
        """Check if a new sandbox can be created without exceeding limits."""
        return self.active_count < self._max_concurrent_sandboxes

    def queue_sandbox_request(
        self,
        request: dict[str, Any],
    ) -> bool:
        """
        Add a sandbox creation request to the pending queue with size limit.

        Args:
            request: Dict with 'project_path' and optional 'config'

        Returns:
            True if queued successfully, False if queue is full
        """
        # Add timestamp to request for age tracking
        request["_queued_at"] = datetime.now()

        # Clean up old requests first
        self._cleanup_pending_queue()

        # Check queue size limit
        if len(self._pending_queue) >= self.MAX_PENDING_QUEUE_SIZE:
            logger.warning(f"Pending queue full ({self.MAX_PENDING_QUEUE_SIZE}), rejecting request")
            return False

        self._pending_queue.append(request)
        logger.info(f"Queued sandbox request. Queue size: {len(self._pending_queue)}")
        return True

    def _cleanup_pending_queue(self) -> int:
        """Remove expired requests from pending queue."""
        now = datetime.now()
        original_size = len(self._pending_queue)

        self._pending_queue = [
            req
            for req in self._pending_queue
            if (now - req.get("_queued_at", now)).total_seconds() < self.MAX_PENDING_REQUEST_AGE
        ]

        removed = original_size - len(self._pending_queue)
        if removed > 0:
            logger.info(f"Removed {removed} expired requests from pending queue")
        return removed

    def has_pending_requests(self) -> bool:
        """Check if there are pending sandbox creation requests."""
        return len(self._pending_queue) > 0

    async def process_pending_queue(self) -> None:
        """
        Process pending sandbox creation requests.

        Creates sandboxes from the queue while slots are available.
        Automatically cleans up expired requests.
        """
        # Clean up old requests first
        self._cleanup_pending_queue()

        while self._pending_queue and self.can_create_sandbox():
            request = self._pending_queue.pop(0)
            project_path = request.get("project_path")
            config = request.get("config")
            project_id = request.get("project_id")
            tenant_id = request.get("tenant_id")

            try:
                await self.create_sandbox(
                    project_path=str(project_path or ""),
                    config=config,
                    project_id=project_id,
                    tenant_id=tenant_id,
                )
                logger.info(f"Created queued sandbox for {project_path}")
            except Exception as e:
                logger.error(f"Failed to create queued sandbox: {e}")

    # === Activity Tracking ===

    async def update_activity(self, sandbox_id: str) -> None:
        """
        Update the last activity timestamp for a sandbox.

        Args:
            sandbox_id: Sandbox identifier
        """
        async with self._instance_lock:
            instance = self._active_sandboxes.get(sandbox_id)
            if instance:
                instance.last_activity_at = datetime.now()

    def get_idle_time(self, sandbox_id: str) -> timedelta:
        """
        Get the idle time for a sandbox.

        Args:
            sandbox_id: Sandbox identifier

        Returns:
            timedelta since last activity (0 if never active)
        """
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance or not instance.last_activity_at:
            return timedelta(0)

        return datetime.now() - instance.last_activity_at

    # === Enhanced Cleanup ===

    async def cleanup_idle_sandboxes(
        self,
        max_idle_minutes: int = 30,
        min_age_minutes: int = 10,
    ) -> int:
        """
        Clean up sandboxes that have been idle for too long.

        Args:
            max_idle_minutes: Maximum idle time before cleanup
            min_age_minutes: Minimum age before considering for cleanup
                           (prevents cleaning up very new sandboxes)

        Returns:
            Number of sandboxes cleaned up
        """
        now = datetime.now()
        cleanup_ids = []

        for sandbox_id, instance in self._active_sandboxes.items():
            # Check age
            age = (now - instance.created_at).total_seconds() / 60
            if age < min_age_minutes:
                continue

            # Check idle time
            idle_time = self.get_idle_time(sandbox_id)
            idle_minutes = idle_time.total_seconds() / 60

            # Update activity for healthy sandboxes via health check
            if instance.status == SandboxStatus.RUNNING:
                try:
                    is_healthy = await self.health_check(sandbox_id)
                    if is_healthy:
                        # Health check passes, update activity
                        await self.update_activity(sandbox_id)
                    elif idle_minutes >= max_idle_minutes:
                        # Unhealthy and idle
                        cleanup_ids.append(sandbox_id)
                except Exception as e:
                    logger.warning(f"Health check failed for {sandbox_id}: {e}")
                    if idle_minutes >= max_idle_minutes:
                        cleanup_ids.append(sandbox_id)
            elif idle_minutes >= max_idle_minutes:
                cleanup_ids.append(sandbox_id)

        count = 0
        for sandbox_id in cleanup_ids:
            if await self.terminate_sandbox(sandbox_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} idle sandboxes")

        return count

    # === Resource Limit Validation ===

    def validate_resource_config(
        self,
        config: SandboxConfig,
    ) -> tuple[bool, list[str]]:
        """
        Validate a sandbox configuration against resource limits.

        Args:
            config: Sandbox configuration to validate

        Returns:
            Tuple of (is_valid, list_of_errors)
        """
        errors = []

        # Parse memory limit
        try:
            config_memory_mb = self._parse_memory_limit(config.memory_limit)
            if config_memory_mb > self._max_memory_mb:
                errors.append(
                    f"Memory limit {config.memory_limit} ({config_memory_mb}MB) "
                    f"exceeds maximum {self._max_memory_mb}MB"
                )
        except ValueError as e:
            errors.append(f"Invalid memory limit format: {e}")

        # Parse CPU limit
        try:
            config_cpu = float(config.cpu_limit)
            if config_cpu > self._max_cpu_cores:
                errors.append(
                    f"CPU limit {config.cpu_limit} cores "
                    f"exceeds maximum {self._max_cpu_cores} cores"
                )
        except ValueError as e:
            errors.append(f"Invalid CPU limit format: {e}")

        return (len(errors) == 0, errors)

    def _parse_memory_limit(self, limit: str) -> int:
        """Parse memory limit string to MB."""
        limit = limit.lower().strip()

        if limit.endswith("g") or limit.endswith("gb"):
            return int(float(limit[:-1].replace("gb", "")) * 1024)
        if limit.endswith("m") or limit.endswith("mb"):
            return int(float(limit[:-1].replace("mb", "")))
        if limit.endswith("k") or limit.endswith("kb"):
            return int(float(limit[:-1].replace("kb", "")) / 1024)

        # Assume bytes if no suffix
        return int(limit) // (1024 * 1024)

    # === Resource Monitoring ===

    async def get_total_resource_usage(self) -> dict[str, Any]:
        """
        Get total resource usage across all active sandboxes.

        Returns:
            Dict with total_memory_mb, total_cpu_percent, sandbox_count
        """
        total_memory = 0
        total_cpu = 0.0
        count = 0

        for sandbox_id, instance in self._active_sandboxes.items():
            if instance.status != SandboxStatus.RUNNING:
                continue

            try:
                stats = await self.get_sandbox_stats(sandbox_id)
                total_memory += stats.get("memory_usage", 0) // (1024 * 1024)
                total_cpu += stats.get("cpu_percent", 0.0)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to get stats for {sandbox_id}: {e}")

        return {
            "total_memory_mb": total_memory,
            "total_cpu_percent": round(total_cpu, 2),
            "sandbox_count": count,
        }

    async def get_resource_summary(self) -> dict[str, Any]:
        """
        Get comprehensive resource summary.

        Returns:
            Dict with total_sandboxes, total_memory_mb, total_cpu_percent,
            max_concurrent, pending_requests
        """
        usage = await self.get_total_resource_usage()

        return {
            "total_sandboxes": self.active_count,
            "total_memory_mb": usage["total_memory_mb"],
            "total_cpu_percent": usage["total_cpu_percent"],
            "max_concurrent": self._max_concurrent_sandboxes,
            "pending_requests": len(self._pending_queue),
            "max_memory_mb": self._max_memory_mb,
            "max_cpu_cores": self._max_cpu_cores,
        }

    async def health_check_all(self) -> dict[str, int]:
        """
        Perform health check on all running sandboxes.

        Returns:
            Dict with healthy, unhealthy, total counts
        """
        healthy = 0
        unhealthy = 0
        total = 0

        for sandbox_id in list(self._active_sandboxes.keys()):
            if self._active_sandboxes[sandbox_id].status != SandboxStatus.RUNNING:
                continue

            total += 1
            try:
                if await self.health_check(sandbox_id):
                    healthy += 1
                    # Update activity for healthy sandboxes
                    await self.update_activity(sandbox_id)
                else:
                    unhealthy += 1
            except Exception as e:
                logger.warning(f"Health check failed for {sandbox_id}: {e}")
                unhealthy += 1

        return {
            "healthy": healthy,
            "unhealthy": unhealthy,
            "total": total,
        }

    # === Tool Call Activity Update ===

    async def _remove_old_container(self, sandbox_id: str) -> None:
        """Remove an old container by sandbox_id if it still exists in Docker.

        Used during rebuild to clear exited containers before re-creation.
        """
        loop = asyncio.get_event_loop()
        try:
            old_container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )
            logger.info(f"Removing old container {sandbox_id} before rebuild")
            try:
                await loop.run_in_executor(None, lambda: old_container.remove(force=True))
                logger.info(f"Successfully removed old container {sandbox_id}")
            except Exception as remove_err:
                logger.warning(f"Failed to remove old container: {remove_err}")
        except Exception:
            logger.debug(f"Old container {sandbox_id} not found, proceeding with rebuild")

    def _build_rebuild_container_config(
        self,
        sandbox_id: str,
        config: SandboxConfig,
        old_ports: list[int],
        project_path: str,
        labels: dict[str, str],
    ) -> dict[str, Any]:
        """Build the Docker container.run() kwargs for a rebuild."""
        container_config: dict[str, Any] = {
            "image": self._mcp_image,
            "name": sandbox_id,
            "hostname": sandbox_id,
            "detach": True,
            "restart_policy": {"Name": "on-failure", "MaximumRetryCount": 3},
            "extra_hosts": {sandbox_id: "127.0.0.1"},
            "ports": {
                f"{MCP_WEBSOCKET_PORT}/tcp": old_ports[0] if len(old_ports) > 0 else None,
                f"{DESKTOP_PORT}/tcp": old_ports[1] if len(old_ports) > 1 else None,
                f"{TERMINAL_PORT}/tcp": old_ports[2] if len(old_ports) > 2 else None,
            },
            "environment": {
                "SANDBOX_ID": sandbox_id,
                "MCP_HOST": "0.0.0.0",
                "MCP_PORT": str(MCP_WEBSOCKET_PORT),
                "MCP_WORKSPACE": "/workspace",
                "DESKTOP_PORT": str(DESKTOP_PORT),
                "TERMINAL_PORT": str(TERMINAL_PORT),
                **config.environment,
            },
            "mem_limit": config.memory_limit or self._default_memory_limit,
            "cpu_quota": int(float(config.cpu_limit or self._default_cpu_limit) * 100000),
            "labels": labels,
        }
        if project_path:
            container_config["volumes"] = {project_path: {"bind": "/workspace", "mode": "rw"}}
        if config.network_isolated:
            container_config["network_mode"] = "bridge"
        return container_config

    async def _wait_for_container_running(
        self,
        container: Any,
        sandbox_id: str,
        max_wait: int = 10,
    ) -> None:
        """Wait for a container to reach 'running' status.

        Raises RuntimeError if the container fails to start within max_wait seconds.
        """
        loop = asyncio.get_event_loop()
        for wait_attempt in range(max_wait):
            try:
                await asyncio.wait_for(
                    loop.run_in_executor(None, container.reload),
                    timeout=5.0,
                )
            except TimeoutError:
                logger.warning(
                    f"Container reload timed out for {sandbox_id} "
                    f"(attempt {wait_attempt + 1}/{max_wait})"
                )
            if container.status == "running":
                return
            if wait_attempt < max_wait - 1:
                await asyncio.sleep(1)
        # Container never reached running state
        logger.error(
            f"Rebuilt container {sandbox_id} failed to reach running status, "
            f"final status: {container.status}"
        )
        try:
            logs = container.logs(tail=20).decode("utf-8", errors="ignore")
            logger.error(f"Container logs:\n{logs}")
        except Exception:
            pass
        raise RuntimeError(f"Container {sandbox_id} failed to start")

    @staticmethod
    def _extract_actual_ports(
        container: Any,
    ) -> tuple[int | None, int | None, int | None]:
        """Extract actual host port mappings from a running container."""
        mcp_port = None
        desktop_port = None
        terminal_port = None
        if not container.ports:
            return mcp_port, desktop_port, terminal_port
        port_mappings = container.ports
        for internal_port, attr_name in [
            (MCP_WEBSOCKET_PORT, "mcp"),
            (DESKTOP_PORT, "desktop"),
            (TERMINAL_PORT, "terminal"),
        ]:
            key = f"{internal_port}/tcp"
            host_port = port_mappings.get(key)
            if host_port and len(host_port) > 0:
                port_val = int(host_port[0]["HostPort"])
                if attr_name == "mcp":
                    mcp_port = port_val
                elif attr_name == "desktop":
                    desktop_port = port_val
                else:
                    terminal_port = port_val
        return mcp_port, desktop_port, terminal_port

    async def _rebuild_sandbox(
        self,
        old_instance: MCPSandboxInstance,
    ) -> MCPSandboxInstance | None:
        """
        Rebuild a sandbox container with the same ID.

        Creates a new container with the same configuration and re-maps it
        to the original sandbox ID for transparency.

        Args:
            old_instance: The old sandbox instance to rebuild

        Returns:
            New MCPSandboxInstance or None if rebuild failed
        """
        original_sandbox_id = old_instance.id
        original_config = old_instance.config or SandboxConfig(image=self._mcp_image)
        original_project_path = old_instance.project_path
        original_labels = old_instance.labels
        old_ports = self._get_instance_ports(old_instance)

        # Release old ports before rebuild
        async with self._port_allocation_lock:
            self._release_ports_unsafe(old_ports)

        await self.disconnect_mcp(original_sandbox_id)
        await self._remove_old_container(original_sandbox_id)

        try:
            container_config = self._build_rebuild_container_config(
                original_sandbox_id,
                original_config,
                old_ports,
                original_project_path,
                original_labels,
            )

            loop = asyncio.get_event_loop()
            new_container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.run(**container_config),
            )

            await self._wait_for_container_running(new_container, original_sandbox_id)

            actual_mcp, actual_desktop, actual_terminal = self._extract_actual_ports(new_container)

            websocket_url, desktop_url, terminal_url = self._build_urls_from_ports(
                original_sandbox_id, actual_mcp, actual_desktop, actual_terminal
            )

            now = datetime.now()
            new_instance = MCPSandboxInstance(
                id=original_sandbox_id,
                status=SandboxStatus.RUNNING,
                config=original_config,
                project_path=original_project_path,
                endpoint=websocket_url,
                created_at=now,
                last_activity_at=now,
                websocket_url=websocket_url,
                mcp_client=None,
                mcp_port=actual_mcp,
                desktop_port=actual_desktop,
                terminal_port=actual_terminal,
                desktop_url=desktop_url,
                terminal_url=terminal_url,
                labels=original_labels,
            )

            logger.info(
                f"Successfully rebuilt sandbox {original_sandbox_id} "
                f"(MCP: {actual_mcp}, Desktop: {actual_desktop}, Terminal: {actual_terminal})"
            )

            async with self._instance_lock:
                self._active_sandboxes[original_sandbox_id] = new_instance
            async with self._port_allocation_lock:
                self._track_ports(actual_mcp, actual_desktop, actual_terminal)

            return new_instance

        except Exception as e:
            logger.error(f"Failed to rebuild sandbox {original_sandbox_id}: {e}")
            return None

    async def _attempt_sandbox_rebuild(
        self,
        sandbox_id: str,
        instance: MCPSandboxInstance,
    ) -> bool:
        """Attempt to rebuild an unhealthy sandbox and reconnect MCP.
        Checks rebuild cooldown, performs rebuild, and connects MCP client.

        Returns:
            True if rebuild and reconnection succeeded.
        """
        import time as time_module

        now = time_module.time()
        last_rebuild = await self._last_rebuild_at.get(sandbox_id)
        last_rebuild = last_rebuild or 0.0
        if now - last_rebuild < self._rebuild_cooldown_seconds:
            logger.warning(
                f"Sandbox {sandbox_id} is unhealthy but rebuild was attempted "
                f"recently ({now - last_rebuild:.1f}s ago), skipping rebuild to prevent loop. "
                f"Cooldown: {self._rebuild_cooldown_seconds}s"
            )
            return False

        logger.warning(
            f"Sandbox {sandbox_id} is unhealthy (status={instance.status}), "
            f"attempting to rebuild..."
        )
        await self._last_rebuild_at.set(sandbox_id, now)
        new_instance = await self._rebuild_sandbox(instance)
        if new_instance is None:
            return False

        try:
            connected = await self.connect_mcp(sandbox_id)
            if not connected:
                logger.warning(f"MCP connection failed after rebuilding sandbox {sandbox_id}")
                return False
        except Exception as e:
            logger.error(f"MCP connection error after rebuild: {e}")
            return False

        return True

    async def _ensure_sandbox_healthy(
        self,
        sandbox_id: str,
    ) -> bool:
        """
        Ensure sandbox container is healthy, rebuilding if necessary.
        If the container is dead or unhealthy, it attempts to rebuild it.
        will attempt to sync it from Docker. This handles the case where the
        sandbox was created/recreated by another process (e.g., API server using
        ProjectSandboxLifecycleService while Agent Worker is running).
        Args:
            sandbox_id: Sandbox identifier
        Returns:
            True if sandbox is healthy or was successfully rebuilt
        """
        instance = self._active_sandboxes.get(sandbox_id)
        # If sandbox not in memory, try to sync from Docker
        if not instance:
            logger.info(
                f"Sandbox {sandbox_id} not found in memory, attempting to sync from Docker..."
            )
            instance = await self.sync_sandbox_from_docker(sandbox_id)
            if not instance:
                logger.warning(
                    f"Sandbox {sandbox_id} not found in Docker either, cannot ensure health"
                )
                return False
            logger.info(f"Successfully synced sandbox {sandbox_id} from Docker")
        # skip the expensive Docker API call.
        last_healthy = await self._last_healthy_at.get(sandbox_id)
        if last_healthy and instance.mcp_client and instance.mcp_client.is_connected:
            return True
        # Full health check (includes Docker API call)
        is_healthy = await self.health_check(sandbox_id)
        if is_healthy:
            await self._last_healthy_at.set(sandbox_id, True)
            return True
        # Container is unhealthy - attempt rebuild
        return await self._attempt_sandbox_rebuild(sandbox_id, instance)

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 60.0,
        max_retries: int = 2,
    ) -> dict[str, Any]:
        """
        Call an MCP tool on the sandbox with retry on connection errors.

        Automatically rebuilds the sandbox container if it is dead or unhealthy.

        Args:
            sandbox_id: Sandbox identifier
            tool_name: Name of the tool (read, write, edit, glob, grep, bash)
            arguments: Tool arguments
            timeout: Execution timeout (default 60s, use 15-20s for fast-fail operations)
            max_retries: Maximum retry attempts for connection errors

        Returns:
            Tool execution result
        """
        # Ensure sandbox is healthy before proceeding
        is_healthy = await self._ensure_sandbox_healthy(sandbox_id)
        if not is_healthy:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": f"Sandbox {sandbox_id} is unavailable and could not be rebuilt",
                    }
                ],
                "is_error": True,
            }

        # Update activity before tool call
        await self.update_activity(sandbox_id)

        # Refresh instance reference after potential rebuild (under lock for safety)
        async with self._instance_lock:
            instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {sandbox_id}",
                sandbox_id=sandbox_id,
                operation="call_tool",
            )

        for attempt in range(max_retries):
            try:
                # Auto-connect if needed
                if not instance.mcp_client or not instance.mcp_client.is_connected:
                    connected = await self.connect_mcp(sandbox_id)
                    if not connected:
                        raise SandboxConnectionError(
                            message="Failed to connect MCP client",
                            sandbox_id=sandbox_id,
                            operation="call_tool",
                        )

                result = await instance.mcp_client.call_tool(
                    tool_name,
                    arguments,
                    timeout=timeout,
                )

                # Update activity after successful call
                await self.update_activity(sandbox_id)

                return {
                    "content": result.content,
                    "is_error": result.isError,
                    "artifact": result.artifact,  # Preserve artifact data from export_artifact
                }

            except (SandboxConnectionError, ConnectionError) as e:
                # Invalidate health cache so next call_tool does a full check
                await self._last_healthy_at.delete(sandbox_id)
                if attempt < max_retries - 1:
                    logger.warning(
                        f"Tool call connection error (attempt {attempt + 1}/{max_retries}): {e}. "
                        f"Retrying..."
                    )
                    # Force reconnect on next attempt
                    if instance.mcp_client:
                        await instance.mcp_client.disconnect()
                        instance.mcp_client = None
                    await asyncio.sleep(1.0 * (attempt + 1))
                else:
                    # Final attempt failed, return error
                    logger.error(f"Tool call failed after {max_retries} attempts: {e}")
                    return {
                        "content": [
                            {
                                "type": "text",
                                "text": f"Connection error after {max_retries} attempts: {e!s}",
                            }
                        ],
                        "is_error": True,
                    }
            except Exception as e:
                # Non-retryable error
                logger.error(f"Tool call error: {e}")
                return {
                    "content": [{"type": "text", "text": f"Error: {e!s}"}],
                    "is_error": True,
                }

        # Should not reach here, but satisfy mypy
        return {
            "content": [{"type": "text", "text": "Tool call failed: no attempts made"}],
            "is_error": True,
        }
    # === Enhanced Orphan Cleanup ===

    async def _is_container_tracked_in_db(
        self,
        container_name: str,
        project_id: str,
    ) -> bool:
        """Check whether the container is tracked in the database.

        Returns True if the container is associated in the DB and should be kept.
        """
        try:
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
                SqlProjectSandboxRepository,
            )

            async with async_session_factory() as db:
                repo = SqlProjectSandboxRepository(db)
                assoc = await repo.find_by_project(project_id)
                if assoc and assoc.sandbox_id == container_name:
                    return True
        except Exception as e:
            logger.warning(f"DB check failed for container {container_name}: {e}")
        return False

    @staticmethod
    def _is_container_age_exceeded(
        container: Any,
        max_age_hours: int,
        now: datetime,
    ) -> bool:
        """Check if a container's age exceeds max_age_hours."""
        try:
            created_str = container.attrs.get("Created", "")
            if not created_str:
                return False
            created_str = created_str.split(".")[0]
            created_at = datetime.fromisoformat(created_str.replace("Z", "+00:00"))
            age_hours = (now - created_at.replace(tzinfo=None)).total_seconds() / 3600
            return age_hours > max_age_hours
        except Exception as e:
            logger.warning(f"Failed to parse container creation time: {e}")
            return False

    async def _classify_container_for_cleanup(
        self,
        container: Any,
        *,
        check_db: bool,
        remove_exited: bool,
        max_age_hours: int | None,
        now: datetime,
    ) -> bool:
        """Determine if a container should be removed during orphan cleanup.

        Returns True if the container should be removed.
        """
        labels = container.labels or {}
        container_name = container.name or container.id[:12]
        status = container.status
        project_id = labels.get("memstack.project_id")

        if not project_id:
            logger.info(
                f"Marking orphan container for cleanup: {container_name} "
                f"(no project_id, status={status})"
            )
            return True

        if remove_exited and status in ("exited", "dead"):
            logger.info(f"Marking exited container for cleanup: {container_name} (status={status})")
            return True

        if container.name not in self._active_sandboxes:
            if check_db and await self._is_container_tracked_in_db(container.name, project_id):
                return False
            logger.info(
                f"Marking untracked container for cleanup: {container_name} "
                f"(project_id={project_id}, not in memory)"
            )
            return True

        if max_age_hours and self._is_container_age_exceeded(container, max_age_hours, now):
            container_name = container.name or container.id[:12]
            logger.info(
                f"Marking ancient container for cleanup: {container_name} "
                f"(age exceeded {max_age_hours}h)"
            )
            return True

        return False

    async def _remove_containers_batch(
        self,
        containers: list[Any],
        loop: asyncio.AbstractEventLoop,
    ) -> int:
        """Remove a batch of containers, updating cleanup stats.

        Returns number of successfully removed containers.
        """
        count = 0
        for container in containers:
            container_name = container.name or container.id[:12]
            try:
                if container.status == "running":
                    await loop.run_in_executor(None, cast(Callable[[], None], lambda c=container: c.stop(timeout=5)))
                await loop.run_in_executor(None, container.remove)
                count += 1
                logger.info(f"Cleaned up orphan container: {container_name}")
            except Exception as e:
                logger.warning(f"Failed to cleanup container {container_name}: {e}")
                self._cleanup_stats["errors"] += 1
        return count

    async def cleanup_orphans(
        self,
        check_db: bool = False,
        remove_exited: bool = True,
        max_age_hours: int | None = None,
    ) -> int:
        """
        Clean up orphan sandbox containers with enhanced filtering.

        Identifies and removes containers that:
        1. Have no project_id label (orphan)
        2. Have exited/dead status (stale)
        3. Are not in _active_sandboxes AND not in DB (stale, if check_db=True)
        4. Are older than max_age_hours (ancient, if specified)

        Args:
            check_db: If True, check DB for project_sandbox associations
            remove_exited: If True, remove containers with exited/dead status
            max_age_hours: If set, remove containers older than this age

        Returns:
            Number of containers cleaned up
        """
        loop = asyncio.get_event_loop()

        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,
                    filters={"label": "memstack.sandbox=true"},
                ),
            )
        except Exception as e:
            logger.error(f"Failed to list containers for cleanup: {e}")
            return 0

        now = datetime.now()
        containers_to_remove = [
            c
            for c in containers
            if await self._classify_container_for_cleanup(
                c,
                check_db=check_db,
                remove_exited=remove_exited,
                max_age_hours=max_age_hours,
                now=now,
            )
        ]

        count = await self._remove_containers_batch(containers_to_remove, loop)

        if count > 0:
            self._cleanup_stats["total_cleanups"] += 1
            self._cleanup_stats["containers_removed"] += count
            self._cleanup_stats["last_cleanup_at"] = datetime.now().isoformat()
            logger.info(f"Cleaned up {count} orphan container(s)")

        return count

    async def start_periodic_cleanup(
        self,
        interval_seconds: float = 300.0,
    ) -> None:
        """
        Start a background task that periodically cleans up orphan containers.

        Args:
            interval_seconds: Time between cleanup runs (default: 5 minutes)
        """
        # Stop any existing cleanup task
        await self.stop_periodic_cleanup()

        self._cleanup_interval_seconds = interval_seconds

        async def cleanup_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(self._cleanup_interval_seconds)
                    logger.debug("Running periodic orphan cleanup...")
                    await self.cleanup_orphans(check_db=True)
                except asyncio.CancelledError:
                    logger.info("Periodic cleanup task cancelled")
                    break
                except Exception as e:
                    logger.error(f"Periodic cleanup error: {e}")

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info(f"Started periodic cleanup task (interval={interval_seconds}s)")

    async def stop_periodic_cleanup(self) -> None:
        """Stop the periodic cleanup background task."""
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
            logger.info("Stopped periodic cleanup task")

    async def cleanup_on_startup(self) -> int:
        """
        Perform cleanup of orphan containers during adapter startup.

        This should be called once when the adapter initializes to clean up
        any leftover containers from previous sessions.

        Returns:
            Number of containers cleaned up
        """
        logger.info("Running startup cleanup for orphan containers...")

        # Clean up:
        # 1. Containers without project_id (orphan)
        # 2. Exited/dead containers (stale)
        count = await self.cleanup_orphans(
            check_db=False,  # Don't check DB on startup (DB might not be ready)
            remove_exited=True,
        )

        if count > 0:
            logger.info(f"Startup cleanup removed {count} orphan container(s)")
        else:
            logger.info("Startup cleanup: no orphan containers found")

        return count

    def get_cleanup_stats(self) -> dict[str, Any]:
        """
        Get cleanup statistics.

        Returns:
            Dict with total_cleanups, containers_removed, last_cleanup_at, errors
        """
        return dict(self._cleanup_stats)

    # === MCP Server Health Check ===

    async def start_mcp_server_health_check(
        self,
        interval_seconds: float = 60.0,
    ) -> None:
        """
        Start a background task that periodically checks MCP server health.

        Args:
            interval_seconds: Time between health checks (default: 1 minute)
        """
        # Stop any existing health check task
        await self.stop_mcp_server_health_check()

        self._health_check_interval_seconds = interval_seconds

        async def health_check_loop() -> None:
            while True:
                try:
                    await asyncio.sleep(self._health_check_interval_seconds)
                    await self._run_health_check_cycle()
                except asyncio.CancelledError:
                    logger.info("MCP server health check task cancelled")
                    break
                except Exception as e:
                    logger.error(f"MCP server health check error: {e}")
                    self._health_check_stats["errors"] += 1

        self._health_check_task = asyncio.create_task(health_check_loop())
        logger.info(f"Started MCP server health check task (interval={interval_seconds}s)")

    async def stop_mcp_server_health_check(self) -> None:
        """Stop the MCP server health check background task."""
        if self._health_check_task is not None:
            self._health_check_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_check_task
            self._health_check_task = None
            logger.info("Stopped MCP server health check task")

    async def _run_health_check_cycle(self) -> None:
        """Run a single health check cycle for all active sandboxes."""
        self._health_check_stats["total_checks"] += 1
        self._health_check_stats["last_check_at"] = datetime.now().isoformat()

        for sandbox_id, _instance in list(self._active_sandboxes.items()):
            try:
                await self._check_mcp_servers_health(sandbox_id, auto_restart=True)
            except Exception as e:
                logger.warning(f"Health check failed for sandbox {sandbox_id}: {e}")

    async def _check_mcp_servers_health(
        self,
        sandbox_id: str,
        auto_restart: bool = False,
    ) -> dict[str, list[str]]:
        """
        Check health of MCP servers running in a sandbox.

        Args:
            sandbox_id: Sandbox container ID
            auto_restart: If True, automatically restart crashed servers

        Returns:
            Dict with 'running', 'crashed', 'restarted' lists of server names
        """
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance or not instance.mcp_client:
            return {"running": [], "crashed": [], "restarted": []}

        result = {"running": [], "crashed": [], "restarted": []}

        try:
            # Call mcp_server_list to get server status
            list_result = await instance.mcp_client.call_tool("mcp_server_list", {})

            # Parse response
            servers = self._parse_mcp_server_list(vars(list_result))

            for server_info in servers:
                server_name = server_info.get("name", "")
                status = server_info.get("status", "unknown")

                if status == "running":
                    result["running"].append(server_name)
                elif status in ("crashed", "exited", "stopped", "error"):
                    result["crashed"].append(server_name)

                    if auto_restart:
                        restarted = await self._restart_crashed_server(sandbox_id, server_name)
                        if restarted:
                            result["restarted"].append(server_name)
                            self._health_check_stats["restarts_triggered"] += 1

        except Exception as e:
            logger.warning(f"Failed to check MCP servers health: {e}")

        return result

    async def _restart_crashed_server(
        self,
        sandbox_id: str,
        server_name: str,
    ) -> bool:
        """
        Restart a crashed MCP server.

        Args:
            sandbox_id: Sandbox container ID
            server_name: Name of the crashed server

        Returns:
            True if restart succeeded, False otherwise
        """
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance or not instance.mcp_client:
            return False

        # Get stored config
        config_key = (sandbox_id, server_name)
        config = self._mcp_server_configs.get(config_key)

        if not config:
            logger.warning(f"No config stored for server {server_name}, cannot restart")
            return False

        try:
            logger.info(f"Restarting crashed MCP server: {server_name}")

            # Call mcp_server_start
            start_result = await instance.mcp_client.call_tool(
                "mcp_server_start",
                {
                    "name": server_name,
                    "server_type": config.get("server_type", "stdio"),
                    "transport_config": config.get("transport_config", "{}"),
                },
            )

            # Check result
            if start_result.get("isError"):
                logger.warning(f"Failed to restart MCP server {server_name}: {start_result}")
                return False

            logger.info(f"Successfully restarted MCP server: {server_name}")
            return True

        except Exception as e:
            logger.error(f"Error restarting MCP server {server_name}: {e}")
            return False

    def store_mcp_server_config(
        self,
        sandbox_id: str,
        server_name: str,
        server_type: str,
        transport_config: str,
    ) -> None:
        """
        Store MCP server config for potential restart.

        Args:
            sandbox_id: Sandbox container ID
            server_name: Name of the server
            server_type: Type of server (stdio, sse, http, websocket)
            transport_config: JSON string of transport config
        """
        config_key = (sandbox_id, server_name)
        self._mcp_server_configs[config_key] = {
            "server_type": server_type,
            "transport_config": transport_config,
        }
        logger.debug(f"Stored config for MCP server {server_name}")

    def _parse_mcp_server_list(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        """Parse server list from mcp_server_list result."""
        import json

        content = result.get("content", [])
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                text = item.get("text", "")
                try:
                    data = json.loads(text)
                    if isinstance(data, dict) and "servers" in data:
                        return cast(list[dict[str, Any]], data["servers"])
                    if isinstance(data, list):
                        return data
                except (json.JSONDecodeError, TypeError):
                    pass
        return []

    def get_health_check_stats(self) -> dict[str, Any]:
        """
        Get health check statistics.

        Returns:
            Dict with total_checks, restarts_triggered, last_check_at, errors
        """
        return dict(self._health_check_stats)

    async def get_or_create_sandbox(
        self,
        project_id: str,
        db_session: AsyncSession | None = None,
    ) -> MCPSandboxInstance | None:
        """Get existing active sandbox or create new one for project.

        This method implements project-level sandbox reuse strategy.

        Args:
            project_id: Project ID to get/create sandbox for
            db_session: Database session (optional, for future use)

        Returns:
            MCPSandboxInstance if successful, None otherwise
        """
        try:
            # 1. Find project's existing sandbox
            async with self._instance_lock:
                for sandbox in self._active_sandboxes.values():
                    if sandbox.project_id == project_id and sandbox.status == SandboxStatus.RUNNING:
                        logger.info(
                            f"Reusing existing sandbox {sandbox.id} for project {project_id}"
                        )
                        return sandbox

            # 2. Create new sandbox
            logger.info(f"Creating new sandbox for project {project_id}")

            # Use workspace_base as host path, mapped to container's /workspace
            host_workspace_path = f"{self._workspace_base}/{project_id}"

            sandbox = await self.create_sandbox(
                project_path=host_workspace_path,  # Host path mapped to container's /workspace
                config=SandboxConfig(
                    image=self._mcp_image,
                    timeout_seconds=self._default_timeout,
                    memory_limit=self._default_memory_limit,
                    cpu_limit=self._default_cpu_limit,
                ),
                project_id=project_id,
            )

            if not sandbox:
                logger.error(f"Failed to create sandbox for project {project_id}")
                return None

            # 3. Connect MCP
            await self.connect_mcp(sandbox.id)

            logger.info(f"Created and connected sandbox {sandbox.id} for project {project_id}")
            return sandbox

        except Exception as e:
            logger.error(
                f"Failed to get/create sandbox for project {project_id}: {e}", exc_info=True
            )
            return None
