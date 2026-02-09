"""MCP Sandbox Adapter - Docker sandbox with MCP WebSocket server.

This adapter creates Docker containers running the sandbox-mcp-server,
enabling file system operations via the MCP protocol over WebSocket.
"""

import asyncio
import logging
import socket
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Set

import docker
from docker.errors import ImageNotFound, NotFound

from src.domain.ports.services.sandbox_port import (
    CodeExecutionRequest,
    CodeExecutionResult,
    SandboxConfig,
    SandboxConnectionError,
    SandboxInstance,
    SandboxNotFoundError,
    SandboxPort,
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

    mcp_client: Optional[MCPWebSocketClient] = None
    websocket_url: Optional[str] = None
    # Service ports on host
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    # Service URLs
    desktop_url: Optional[str] = None
    terminal_url: Optional[str] = None


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
    ):
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
        """
        self._mcp_image = mcp_image
        self._default_timeout = default_timeout
        self._default_memory_limit = default_memory_limit
        self._default_cpu_limit = default_cpu_limit
        self._host_port_start = host_port_start
        self._desktop_port_start = desktop_port_start
        self._terminal_port_start = terminal_port_start

        # Resource limits
        self._max_concurrent_sandboxes = max_concurrent_sandboxes
        self._max_memory_mb = max_memory_mb
        self._max_cpu_cores = max_cpu_cores

        # Thread-safe lock for shared state access
        self._lock = asyncio.Lock()

        # Track active sandboxes and port allocation
        self._active_sandboxes: Dict[str, MCPSandboxInstance] = {}
        self._port_counter = 0
        self._desktop_port_counter = 0
        self._terminal_port_counter = 0
        self._used_ports: Set[int] = set()

        # Pending queue for sandbox creation requests
        self._pending_queue: List[Dict[str, Any]] = []

        # Track cleanup state to prevent double cleanup
        self._cleanup_in_progress: Set[str] = set()

        # Track rebuild timestamps using TTL cache to prevent memory leaks
        # Old entries auto-expire after rebuild_ttl_seconds
        from src.infrastructure.adapters.secondary.sandbox.health_monitor import TTLCache

        self._rebuild_cooldown_seconds = 5.0  # Minimum seconds between rebuilds
        self._rebuild_ttl_seconds = 300.0  # Entries expire after 5 minutes
        self._last_rebuild_at: TTLCache = TTLCache(
            default_ttl_seconds=self._rebuild_ttl_seconds,
            max_size=1000,
        )

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
            )

    def _is_port_available(self, port: int) -> bool:
        """Check if a port is available on the host.

        Performs two checks:
        1. Checks if port is already in use by existing Docker containers
        2. Attempts to bind to the port to verify it's free

        Args:
            port: The port number to check

        Returns:
            True if port is available, False otherwise
        """
        # Check if port is in our tracking set
        if port in self._used_ports:
            return False

        # Check if port is used by existing Docker containers
        try:
            containers = self._docker.containers.list(all=True)
            for container in containers:
                # Check container port mappings
                ports = container.ports or {}
                for port_mappings in ports.values():
                    if port_mappings:
                        for mapping in port_mappings:
                            host_port = mapping.get("HostPort")
                            if host_port and int(host_port) == port:
                                return False
        except Exception as e:
            logger.warning(f"Error checking Docker container ports: {e}")

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

    def _release_ports_unsafe(self, ports: List[int]) -> None:
        """Release ports when sandbox is terminated (must be called with lock held)."""
        for port in ports:
            self._used_ports.discard(port)

    async def create_sandbox(
        self,
        project_path: str,
        config: Optional[SandboxConfig] = None,
        project_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        sandbox_id: Optional[str] = None,
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
        # Use provided sandbox_id or generate a new one
        sandbox_id = sandbox_id or f"mcp-sandbox-{uuid.uuid4().hex[:12]}"

        # Check and cleanup any existing containers for this project
        if project_id:
            await self.cleanup_project_containers(project_id)

        # Allocate ports for all services with lock protection
        async with self._lock:
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

            async with self._lock:
                self._active_sandboxes[sandbox_id] = instance
            logger.info(
                f"Created MCP sandbox: {sandbox_id} "
                f"(MCP: {host_mcp_port}, Desktop: {host_desktop_port}, Terminal: {host_terminal_port})"
            )

            return instance

        except ImageNotFound:
            # Release allocated ports on failure
            async with self._lock:
                self._release_ports_unsafe([host_mcp_port, host_desktop_port, host_terminal_port])
            logger.error(f"MCP sandbox image not found: {self._mcp_image}")
            raise SandboxConnectionError(
                message=f"Docker image not found: {self._mcp_image}. "
                f"Build with: cd sandbox-mcp-server && docker build -t {self._mcp_image} .",
                sandbox_id=sandbox_id,
                operation="create",
            )
        except Exception as e:
            # Release allocated ports on failure
            async with self._lock:
                self._release_ports_unsafe([host_mcp_port, host_desktop_port, host_terminal_port])
            logger.error(f"Failed to create MCP sandbox: {e}")
            raise SandboxConnectionError(
                message=f"Failed to create sandbox: {e}",
                sandbox_id=sandbox_id,
                operation="create",
            )

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

        # Verify container is running before attempting connection
        try:
            container = self._docker.containers.get(sandbox_id)
            if container.status != "running":
                logger.warning(
                    f"Sandbox {sandbox_id} container not running (status={container.status}), "
                    "connection will fail. Caller should trigger rebuild first."
                )
                return False
        except Exception:
            logger.warning(f"Sandbox {sandbox_id} container not found")
            return False

        # Refresh instance reference
        instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            logger.error(f"Sandbox {sandbox_id} not found")
            return False

        # Create MCP client
        client = MCPWebSocketClient(
            url=instance.websocket_url,
            timeout=timeout,
            heartbeat_interval=30.0,
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

    async def list_tools(self, sandbox_id: str) -> List[Dict[str, Any]]:
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
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.inputSchema,
            }
            for t in tools
        ]

    # === SandboxPort interface implementation ===

    async def get_sandbox(self, sandbox_id: str) -> Optional[MCPSandboxInstance]:
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
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            # Container exists but not in memory - recover it
            if container.status == "running":
                logger.info(f"Recovering sandbox {sandbox_id} from Docker (API restart)")
                
                labels = container.labels or {}
                
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
                    from src.infrastructure.adapters.secondary.sandbox.url_service import (
                        SandboxInstanceInfo,
                        SandboxUrlService,
                    )
                    url_service = SandboxUrlService()
                    instance_info = SandboxInstanceInfo(
                        mcp_port=mcp_port,
                        desktop_port=desktop_port or 0,
                        terminal_port=terminal_port or 0,
                        sandbox_id=sandbox_id,
                        host="localhost",
                    )
                    urls = url_service.build_all_urls(instance_info)
                    websocket_url = urls.mcp_url
                    desktop_url = urls.desktop_url if desktop_port else None
                    terminal_url = urls.terminal_url if terminal_port else None

                # Create instance record
                from datetime import datetime
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

                async with self._lock:
                    self._active_sandboxes[sandbox_id] = instance
                    # Track used ports
                    if mcp_port:
                        self._used_ports.add(mcp_port)
                    if desktop_port:
                        self._used_ports.add(desktop_port)
                    if terminal_port:
                        self._used_ports.add(terminal_port)

                logger.info(f"Successfully recovered sandbox {sandbox_id} (MCP: {mcp_port}, Desktop: {desktop_port}, Terminal: {terminal_port})")
                return instance
            else:
                # Container exists but not running
                return None

        except NotFound:
            # Container doesn't exist in Docker either
            return None
        except Exception as e:
            logger.warning(f"Error recovering sandbox {sandbox_id} from Docker: {e}")
            return None

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Terminate a sandbox container with proper cleanup and locking."""
        # Prevent double cleanup with lock
        async with self._lock:
            if sandbox_id in self._cleanup_in_progress:
                logger.warning(f"Cleanup already in progress for sandbox: {sandbox_id}")
                return False
            self._cleanup_in_progress.add(sandbox_id)

        try:
            # Get instance before deletion to release ports
            instance = self._active_sandboxes.get(sandbox_id)
            ports_to_release = []
            if instance:
                ports_to_release = [
                    instance.mcp_port,
                    instance.desktop_port,
                    instance.terminal_port,
                ]
                ports_to_release = [p for p in ports_to_release if p is not None]

            # Disconnect MCP client first
            await self.disconnect_mcp(sandbox_id)

            # Stop and remove container with timeout protection
            loop = asyncio.get_event_loop()
            try:
                container = await loop.run_in_executor(
                    None,
                    lambda: self._docker.containers.get(sandbox_id),
                )

                # Stop container with timeout protection
                try:
                    await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: container.stop(timeout=5)),
                        timeout=15.0,  # Overall timeout for stop operation
                    )
                except asyncio.TimeoutError:
                    logger.warning(f"Container stop timed out for {sandbox_id}, forcing kill")
                    try:
                        await loop.run_in_executor(None, container.kill)
                    except Exception as kill_err:
                        logger.warning(f"Force kill failed for {sandbox_id}: {kill_err}")

                # Remove container
                try:
                    await loop.run_in_executor(None, container.remove)
                except Exception as rm_err:
                    logger.warning(f"Container remove failed for {sandbox_id}: {rm_err}")
                    # Try force remove
                    try:
                        await loop.run_in_executor(None, lambda: container.remove(force=True))
                    except Exception:
                        pass

            except NotFound:
                logger.warning(f"Container not found for termination: {sandbox_id}")

            # Always update tracking and release ports with lock
            async with self._lock:
                if sandbox_id in self._active_sandboxes:
                    self._active_sandboxes[sandbox_id].status = SandboxStatus.TERMINATED
                    self._active_sandboxes[sandbox_id].terminated_at = datetime.now()
                    del self._active_sandboxes[sandbox_id]
                # Release ports
                self._release_ports_unsafe(ports_to_release)

            logger.info(f"Terminated MCP sandbox: {sandbox_id}")
            return True

        except Exception as e:
            logger.error(f"Error terminating sandbox {sandbox_id}: {e}")
            # Ensure cleanup even on error - release ports to prevent leak
            async with self._lock:
                instance = self._active_sandboxes.get(sandbox_id)
                if instance:
                    ports_to_release = [
                        instance.mcp_port,
                        instance.desktop_port,
                        instance.terminal_port,
                    ]
                    ports_to_release = [p for p in ports_to_release if p is not None]
                    self._release_ports_unsafe(ports_to_release)
                    del self._active_sandboxes[sandbox_id]
            return False
        finally:
            # Always remove from cleanup tracking
            async with self._lock:
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
            return container.status == "running"
        except NotFound:
            # Container doesn't exist
            return False
        except Exception as e:
            logger.warning(f"Error checking container existence for {sandbox_id}: {e}")
            return False

    async def get_sandbox_id_by_project(self, project_id: str) -> Optional[str]:
        """Get sandbox ID for a specific project.

        Searches active sandboxes for one associated with the given project ID.

        Args:
            project_id: The project ID to look up

        Returns:
            The sandbox ID if found, None otherwise
        """
        if not project_id:
            return None

        async with self._lock:
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
                return labels.get("memstack.sandbox.id")
        except Exception as e:
            logger.warning(f"Error looking up sandbox by project: {e}")

        return None

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

            mount_pattern = f"memstack_{project_id}"
            for container in all_sandbox_containers:
                try:
                    # Check container mounts
                    mounts = container.attrs.get("Mounts", [])
                    for mount in mounts:
                        source = mount.get("Source", "")
                        if mount_pattern in source:
                            containers_to_cleanup.add(container.id)
                            break

                    # Also check container name
                    container_name = container.name or ""
                    if mount_pattern in container_name or project_id in container_name:
                        containers_to_cleanup.add(container.id)
                except Exception as e:
                    logger.warning(f"Error checking container {container.id}: {e}")

            if not containers_to_cleanup:
                return 0

            logger.info(
                f"Found {len(containers_to_cleanup)} container(s) for project {project_id}, cleaning up..."
            )

            # Get container objects and clean up
            for container_id in containers_to_cleanup:
                try:
                    container = self._docker.containers.get(container_id)
                    container_name = container.name or container_id

                    # Stop if running
                    if container.status == "running":
                        try:
                            await asyncio.wait_for(
                                loop.run_in_executor(None, lambda c=container: c.stop(timeout=5)),
                                timeout=10.0,
                            )
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"Stop timed out for container {container_name}, forcing kill"
                            )
                            await loop.run_in_executor(None, container.kill)

                    # Remove container
                    await loop.run_in_executor(None, lambda c=container: c.remove(force=True))

                    # Clean up from internal tracking
                    async with self._lock:
                        if container_name in self._active_sandboxes:
                            instance = self._active_sandboxes[container_name]
                            ports_to_release = [
                                instance.mcp_port,
                                instance.desktop_port,
                                instance.terminal_port,
                            ]
                            ports_to_release = [p for p in ports_to_release if p is not None]
                            self._release_ports_unsafe(ports_to_release)
                            del self._active_sandboxes[container_name]

                    terminated_count += 1
                    logger.info(f"Cleaned up container {container_name} for project {project_id}")

                except Exception as e:
                    logger.warning(f"Failed to cleanup container {container_id}: {e}")

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
    ) -> AsyncIterator[Dict[str, Any]]:
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
        status: Optional[SandboxStatus] = None,
    ) -> List[MCPSandboxInstance]:
        """List all sandbox instances (thread-safe)."""
        async with self._lock:
            result = []
            for instance in list(self._active_sandboxes.values()):
                if status is None or instance.status == status:
                    result.append(instance)
            return result

    async def sync_sandbox_from_docker(self, sandbox_id: str) -> Optional[MCPSandboxInstance]:
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

            async with self._lock:
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
            async with self._lock:
                for container in containers:
                    # Skip already tracked containers
                    if container.name in self._active_sandboxes:
                        continue

                    # Skip non-running containers
                    if container.status != "running":
                        continue

                    labels = container.labels or {}
                    sandbox_id = labels.get("memstack.sandbox.id", container.name)

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
                        config=SandboxConfig(
                            image=self._mcp_image
                        ),  # Default config for discovered containers
                        project_path=project_path,
                        endpoint=websocket_url,
                        created_at=now,  # Approximation
                        last_activity_at=now,
                        websocket_url=websocket_url,
                        mcp_client=None,  # Will connect on first use
                        mcp_port=mcp_port,
                        desktop_port=desktop_port,
                        terminal_port=terminal_port,
                        desktop_url=desktop_url,
                        terminal_url=terminal_url,
                        labels=labels,  # Full labels including project_id/tenant_id
                    )

                    self._active_sandboxes[sandbox_id] = instance

                    # Track used ports
                    if mcp_port:
                        self._used_ports.add(mcp_port)
                    if desktop_port:
                        self._used_ports.add(desktop_port)
                    if terminal_port:
                        self._used_ports.add(terminal_port)

                    count += 1
                    logger.info(
                        f"Discovered existing sandbox: {sandbox_id} "
                        f"(project_id={labels.get('memstack.project_id', 'unknown')})"
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
    ) -> Dict[str, bytes]:
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
        async with self._lock:
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

    async def get_sandbox_stats(self, sandbox_id: str, project_id: str = None) -> Dict[str, Any]:
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
                        await loop.run_in_executor(None, lambda: container.stop(timeout=5))
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
        request: Dict[str, Any],
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
                    project_path=project_path,
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
    ) -> tuple[bool, List[str]]:
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

    async def get_total_resource_usage(self) -> Dict[str, Any]:
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

    async def get_resource_summary(self) -> Dict[str, Any]:
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

    async def health_check_all(self) -> Dict[str, int]:
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

    async def _rebuild_sandbox(
        self,
        old_instance: MCPSandboxInstance,
    ) -> Optional[MCPSandboxInstance]:
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
        original_config = old_instance.config
        original_project_path = old_instance.project_path
        original_labels = old_instance.labels

        # Store port info to release old container's ports
        old_ports = [
            old_instance.mcp_port,
            old_instance.desktop_port,
            old_instance.terminal_port,
        ]
        old_ports = [p for p in old_ports if p is not None]

        # Clean up the old instance
        await self.disconnect_mcp(original_sandbox_id)

        # IMPORTANT: Remove the old container if it still exists
        # When a container is killed, it still exists in Docker (exited state)
        # We need to remove it before we can create a new one with the same name
        loop = asyncio.get_event_loop()
        try:
            old_container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(original_sandbox_id),
            )
            # Container exists - remove it first
            logger.info(f"Removing old container {original_sandbox_id} before rebuild")
            try:
                await loop.run_in_executor(None, lambda: old_container.remove(force=True))
                logger.info(f"Successfully removed old container {original_sandbox_id}")
            except Exception as remove_err:
                logger.warning(f"Failed to remove old container: {remove_err}")
        except Exception:
            # Container doesn't exist, which is fine
            logger.debug(f"Old container {original_sandbox_id} not found, proceeding with rebuild")

        # Create new container with the original ID directly
        try:
            config = original_config or SandboxConfig(image=self._mcp_image)

            # Build service URLs
            from src.infrastructure.adapters.secondary.sandbox.url_service import (
                SandboxInstanceInfo,
                SandboxUrlService,
            )

            instance_info = SandboxInstanceInfo(
                mcp_port=old_ports[0] if len(old_ports) > 0 else None,
                desktop_port=old_ports[1] if len(old_ports) > 1 else None,
                terminal_port=old_ports[2] if len(old_ports) > 2 else None,
                sandbox_id=original_sandbox_id,
                host="localhost",
            )
            url_service = SandboxUrlService(default_host="localhost", api_base="/api/v1")
            urls = url_service.build_all_urls(instance_info)

            # Container configuration with original ID and preserved ports
            container_config = {
                "image": self._mcp_image,
                "name": original_sandbox_id,
                "hostname": original_sandbox_id,  # Set hostname for VNC hostname resolution
                "detach": True,
                # Auto-restart policy for container-level recovery (preserved in rebuild)
                "restart_policy": {"Name": "on-failure", "MaximumRetryCount": 3},
                # Add extra hosts to resolve the container hostname (required for VNC)
                "extra_hosts": {original_sandbox_id: "127.0.0.1"},
                "ports": {
                    f"{MCP_WEBSOCKET_PORT}/tcp": old_ports[0] if len(old_ports) > 0 else None,
                    f"{DESKTOP_PORT}/tcp": old_ports[1] if len(old_ports) > 1 else None,
                    f"{TERMINAL_PORT}/tcp": old_ports[2] if len(old_ports) > 2 else None,
                },
                "environment": {
                    "SANDBOX_ID": original_sandbox_id,
                    "MCP_HOST": "0.0.0.0",
                    "MCP_PORT": str(MCP_WEBSOCKET_PORT),
                    "MCP_WORKSPACE": "/workspace",
                    "DESKTOP_PORT": str(DESKTOP_PORT),
                    "TERMINAL_PORT": str(TERMINAL_PORT),
                    **config.environment,
                },
                "mem_limit": config.memory_limit or self._default_memory_limit,
                "cpu_quota": int(float(config.cpu_limit or self._default_cpu_limit) * 100000),
                "labels": original_labels,
            }

            # Volume mounts
            volumes = {}
            if original_project_path:
                volumes[original_project_path] = {"bind": "/workspace", "mode": "rw"}
            if volumes:
                container_config["volumes"] = volumes

            # Network mode
            if config.network_isolated:
                container_config["network_mode"] = "bridge"

            # Run container with original ID
            loop = asyncio.get_event_loop()
            new_container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.run(**container_config),
            )

            # CRITICAL: Verify container is actually running
            # Container might be created but fail to start (e.g., port conflicts)
            max_wait = 10  # Wait up to 10 seconds for container to be running
            for wait_attempt in range(max_wait):
                new_container.reload()  # Refresh container status
                if new_container.status == "running":
                    break
                if wait_attempt < max_wait - 1:
                    await asyncio.sleep(1)
            else:
                # Container never reached running state
                logger.error(
                    f"Rebuilt container {original_sandbox_id} failed to reach running status, "
                    f"final status: {new_container.status}"
                )
                # Try to get container logs for debugging
                try:
                    logs = new_container.logs(tail=20).decode("utf-8", errors="ignore")
                    logger.error(f"Container logs:\n{logs}")
                except Exception:
                    pass
                raise RuntimeError(f"Container {original_sandbox_id} failed to start")

            # Extract actual port mappings from the new container
            # Docker may assign different ports than requested if conflicts occur
            actual_mcp_port = None
            actual_desktop_port = None
            actual_terminal_port = None

            # Container.ports format: {'18765/tcp': [{'HostPort': '18765'}]}
            if new_container.ports:
                port_mappings = new_container.ports
                if f"{MCP_WEBSOCKET_PORT}/tcp" in port_mappings:
                    host_port = port_mappings[f"{MCP_WEBSOCKET_PORT}/tcp"]
                    if host_port and len(host_port) > 0:
                        actual_mcp_port = int(host_port[0]["HostPort"])
                if f"{DESKTOP_PORT}/tcp" in port_mappings:
                    host_port = port_mappings[f"{DESKTOP_PORT}/tcp"]
                    if host_port and len(host_port) > 0:
                        actual_desktop_port = int(host_port[0]["HostPort"])
                if f"{TERMINAL_PORT}/tcp" in port_mappings:
                    host_port = port_mappings[f"{TERMINAL_PORT}/tcp"]
                    if host_port and len(host_port) > 0:
                        actual_terminal_port = int(host_port[0]["HostPort"])

            # Rebuild URLs with actual ports
            instance_info = SandboxInstanceInfo(
                mcp_port=actual_mcp_port,
                desktop_port=actual_desktop_port,
                terminal_port=actual_terminal_port,
                sandbox_id=original_sandbox_id,
                host="localhost",
            )
            urls = url_service.build_all_urls(instance_info)

            # Create new instance with actual port mappings
            now = datetime.now()
            new_instance = MCPSandboxInstance(
                id=original_sandbox_id,
                status=SandboxStatus.RUNNING,
                config=config,
                project_path=original_project_path,
                endpoint=urls.mcp_url,
                created_at=now,
                last_activity_at=now,
                websocket_url=urls.mcp_url,
                mcp_client=None,
                mcp_port=actual_mcp_port,
                desktop_port=actual_desktop_port,
                terminal_port=actual_terminal_port,
                desktop_url=urls.desktop_url,
                terminal_url=urls.terminal_url,
                labels=original_labels,
            )

            logger.info(
                f"Successfully rebuilt sandbox {original_sandbox_id} "
                f"(MCP: {actual_mcp_port}, Desktop: {actual_desktop_port}, Terminal: {actual_terminal_port})"
            )

            # Update tracking with original ID
            async with self._lock:
                self._active_sandboxes[original_sandbox_id] = new_instance

            return new_instance

        except Exception as e:
            logger.error(f"Failed to rebuild sandbox {original_sandbox_id}: {e}")
            return None

    async def _ensure_sandbox_healthy(
        self,
        sandbox_id: str,
    ) -> bool:
        """
        Ensure sandbox container is healthy, rebuilding if necessary.

        This method checks if the sandbox container is running and healthy.
        If the container is dead or unhealthy, it attempts to rebuild it.

        IMPORTANT: If the sandbox is not found in _active_sandboxes, this method
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
        # This handles the case where sandbox was created/recreated by another process
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

        # Check health using existing health_check method
        is_healthy = await self.health_check(sandbox_id)

        if is_healthy:
            # Container is healthy, update instance reference
            instance = self._active_sandboxes.get(sandbox_id)
            return True

        # Container is unhealthy - check rebuild cooldown before attempting rebuild
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

        # Attempt rebuild
        logger.warning(
            f"Sandbox {sandbox_id} is unhealthy (status={instance.status}), "
            f"attempting to rebuild..."
        )

        # Record rebuild attempt time before starting rebuild (uses TTL cache)
        await self._last_rebuild_at.set(sandbox_id, now)

        # Rebuild the sandbox with the same ID
        new_instance = await self._rebuild_sandbox(instance)
        if new_instance is None:
            return False

        # Connect MCP to the rebuilt instance
        try:
            connected = await self.connect_mcp(sandbox_id)
            if not connected:
                logger.warning(f"MCP connection failed after rebuilding sandbox {sandbox_id}")
                return False
        except Exception as e:
            logger.error(f"MCP connection error after rebuild: {e}")
            return False

        return True

    async def call_tool(
        self,
        sandbox_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 30.0,
        max_retries: int = 2,
    ) -> Dict[str, Any]:
        """
        Call an MCP tool on the sandbox with retry on connection errors.

        Automatically rebuilds the sandbox container if it is dead or unhealthy.

        Args:
            sandbox_id: Sandbox identifier
            tool_name: Name of the tool (read, write, edit, glob, grep, bash)
            arguments: Tool arguments
            timeout: Execution timeout
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

        # Refresh instance reference after potential rebuild
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
                                "text": f"Connection error after {max_retries} attempts: {str(e)}",
                            }
                        ],
                        "is_error": True,
                    }
            except Exception as e:
                # Non-retryable error
                logger.error(f"Tool call error: {e}")
                return {
                    "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                    "is_error": True,
                }
