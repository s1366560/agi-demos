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

from src.application.services.sandbox_url_service import (
    SandboxInstanceInfo,
    SandboxUrlService,
)
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
from src.infrastructure.adapters.secondary.temporal.mcp.websocket_client import (
    MCPWebSocketClient,
)

logger = logging.getLogger(__name__)


# Default sandbox MCP server image
DEFAULT_MCP_IMAGE = "sandbox-mcp-server:latest"

# WebSocket port inside container
MCP_WEBSOCKET_PORT = 8765
DESKTOP_PORT = 6080  # noVNC
TERMINAL_PORT = 7681  # ttyd


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
        mcp_image: str = DEFAULT_MCP_IMAGE,
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

        # Track active sandboxes and port allocation
        self._active_sandboxes: Dict[str, MCPSandboxInstance] = {}
        self._port_counter = 0
        self._desktop_port_counter = 0
        self._terminal_port_counter = 0
        self._used_ports: set = set()

        # Pending queue for sandbox creation requests
        self._pending_queue: List[Dict[str, Any]] = []

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
                            host_port = mapping.get('HostPort')
                            if host_port and int(host_port) == port:
                                return False
        except Exception as e:
            logger.warning(f"Error checking Docker container ports: {e}")
        
        # Try to bind to the port to verify it's free
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('0.0.0.0', port))
                return True
        except OSError:
            return False

    def _get_next_port(self) -> int:
        """Get next available host port for MCP."""
        for _ in range(1000):
            port = self._host_port_start + self._port_counter
            self._port_counter = (self._port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for MCP")

    def _get_next_desktop_port(self) -> int:
        """Get next available host port for desktop (noVNC)."""
        for _ in range(1000):
            port = self._desktop_port_start + self._desktop_port_counter
            self._desktop_port_counter = (self._desktop_port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for desktop")

    def _get_next_terminal_port(self) -> int:
        """Get next available host port for terminal (ttyd)."""
        for _ in range(1000):
            port = self._terminal_port_start + self._terminal_port_counter
            self._terminal_port_counter = (self._terminal_port_counter + 1) % 1000
            if self._is_port_available(port):
                self._used_ports.add(port)
                return port
        raise RuntimeError("No available ports for terminal")

    def _release_ports(self, ports: List[int]) -> None:
        """Release ports when sandbox is terminated."""
        for port in ports:
            self._used_ports.discard(port)

    async def create_sandbox(
        self,
        project_path: str,
        config: Optional[SandboxConfig] = None,
    ) -> MCPSandboxInstance:
        """
        Create a new MCP sandbox container.

        Args:
            project_path: Path to mount as workspace
            config: Sandbox configuration

        Returns:
            MCPSandboxInstance with MCP endpoint
        """
        config = config or SandboxConfig()
        sandbox_id = f"mcp-sandbox-{uuid.uuid4().hex[:12]}"
        
        # Allocate ports for all services
        host_mcp_port = self._get_next_port()
        host_desktop_port = self._get_next_desktop_port()
        host_terminal_port = self._get_next_terminal_port()

        try:
            # Container configuration with all service ports
            container_config = {
                "image": self._mcp_image,
                "name": sandbox_id,
                "detach": True,
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
                # Security options
                "security_opt": ["no-new-privileges:true"],
                # Labels for identification
                "labels": {
                    "memstack.sandbox": "true",
                    "memstack.sandbox.id": sandbox_id,
                    "memstack.sandbox.mcp_port": str(host_mcp_port),
                    "memstack.sandbox.desktop_port": str(host_desktop_port),
                    "memstack.sandbox.terminal_port": str(host_terminal_port),
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
            )

            self._active_sandboxes[sandbox_id] = instance
            logger.info(
                f"Created MCP sandbox: {sandbox_id} "
                f"(MCP: {host_mcp_port}, Desktop: {host_desktop_port}, Terminal: {host_terminal_port})"
            )

            return instance

        except ImageNotFound:
            logger.error(f"MCP sandbox image not found: {self._mcp_image}")
            raise SandboxConnectionError(
                message=f"Docker image not found: {self._mcp_image}. "
                f"Build with: cd sandbox-mcp-server && docker build -t {self._mcp_image} .",
                sandbox_id=sandbox_id,
                operation="create",
            )
        except Exception as e:
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
        Connect MCP client to sandbox with retry.

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
                    wait_time = backoff_factor * (2 ** attempt)
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
        """Get sandbox instance by ID."""
        if sandbox_id not in self._active_sandboxes:
            return None

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

    async def terminate_sandbox(self, sandbox_id: str) -> bool:
        """Terminate a sandbox container."""
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

            # Stop and remove container
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            await loop.run_in_executor(None, lambda: container.stop(timeout=5))
            await loop.run_in_executor(None, container.remove)

            # Update tracking and release ports
            if sandbox_id in self._active_sandboxes:
                self._active_sandboxes[sandbox_id].status = SandboxStatus.TERMINATED
                self._active_sandboxes[sandbox_id].terminated_at = datetime.now()
                del self._active_sandboxes[sandbox_id]

            # Release ports
            self._release_ports(ports_to_release)

            logger.info(f"Terminated MCP sandbox: {sandbox_id}")
            return True

        except NotFound:
            logger.warning(f"Sandbox not found for termination: {sandbox_id}")
            if sandbox_id in self._active_sandboxes:
                instance = self._active_sandboxes[sandbox_id]
                ports_to_release = [
                    instance.mcp_port,
                    instance.desktop_port,
                    instance.terminal_port,
                ]
                ports_to_release = [p for p in ports_to_release if p is not None]
                self._release_ports(ports_to_release)
                del self._active_sandboxes[sandbox_id]
            return False
        except Exception as e:
            logger.error(f"Error terminating sandbox {sandbox_id}: {e}")
            return False

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
        """List all sandbox instances."""
        result = []
        for instance in self._active_sandboxes.values():
            if status is None or instance.status == status:
                result.append(instance)
        return result

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
        """Clean up expired sandbox instances."""
        now = datetime.now()
        expired_ids = []

        for sandbox_id, instance in self._active_sandboxes.items():
            age = (now - instance.created_at).total_seconds()
            if age > max_age_seconds:
                expired_ids.append(sandbox_id)

        count = 0
        for sandbox_id in expired_ids:
            if await self.terminate_sandbox(sandbox_id):
                count += 1

        if count > 0:
            logger.info(f"Cleaned up {count} expired MCP sandboxes")

        return count

    async def get_sandbox_stats(self, sandbox_id: str) -> Dict[str, Any]:
        """
        Get container resource usage statistics.

        Args:
            sandbox_id: Sandbox identifier

        Returns:
            Dict with cpu_percent, memory_usage, memory_limit, etc.
        """
        try:
            loop = asyncio.get_event_loop()
            container = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.get(sandbox_id),
            )

            stats = container.stats(stream=False)

            # Calculate CPU percentage
            cpu_delta = (
                stats["cpu_stats"]["cpu_usage"]["total_usage"]
                - stats["precpu_stats"]["cpu_usage"]["total_usage"]
            )
            system_delta = (
                stats["cpu_stats"]["system_cpu_usage"]
                - stats["precpu_stats"]["system_cpu_usage"]
            )
            cpu_percent = 0.0
            if system_delta > 0:
                cpu_percent = (cpu_delta / system_delta) * 100.0

            memory_stats = stats.get("memory_stats", {})

            return {
                "cpu_percent": round(cpu_percent, 2),
                "memory_usage": memory_stats.get("usage", 0),
                "memory_limit": memory_stats.get("limit", 1),
                "memory_percent": round(
                    (memory_stats.get("usage", 0) / memory_stats.get("limit", 1)) * 100, 2
                ),
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
                lambda: self._docker.containers.list(
                    filters={"label": "memstack.sandbox=true"}
                ),
            )

            count = 0
            for container in containers:
                if container.name not in self._active_sandboxes:
                    logger.warning(f"Found orphaned sandbox container: {container.name}")
                    try:
                        await loop.run_in_executor(
                            None, lambda: container.stop(timeout=5)
                        )
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
        return sum(
            1 for s in self._active_sandboxes.values()
            if s.status == SandboxStatus.RUNNING
        )

    # === Concurrency Control ===

    def can_create_sandbox(self) -> bool:
        """Check if a new sandbox can be created without exceeding limits."""
        return self.active_count < self._max_concurrent_sandboxes

    def queue_sandbox_request(
        self,
        request: Dict[str, Any],
    ) -> None:
        """
        Add a sandbox creation request to the pending queue.

        Args:
            request: Dict with 'project_path' and optional 'config'
        """
        self._pending_queue.append(request)
        logger.info(
            f"Queued sandbox request. Queue size: {len(self._pending_queue)}"
        )

    def has_pending_requests(self) -> bool:
        """Check if there are pending sandbox creation requests."""
        return len(self._pending_queue) > 0

    async def process_pending_queue(self) -> None:
        """
        Process pending sandbox creation requests.

        Creates sandboxes from the queue while slots are available.
        """
        while self._pending_queue and self.can_create_sandbox():
            request = self._pending_queue.pop(0)
            project_path = request.get("project_path")
            config = request.get("config")

            try:
                await self.create_sandbox(project_path, config)
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

        Args:
            sandbox_id: Sandbox identifier
            tool_name: Name of the tool (read, write, edit, glob, grep, bash)
            arguments: Tool arguments
            timeout: Execution timeout
            max_retries: Maximum retry attempts for connection errors

        Returns:
            Tool execution result
        """
        # Update activity before tool call
        await self.update_activity(sandbox_id)

        instance = self._active_sandboxes.get(sandbox_id)
        if not instance:
            raise SandboxNotFoundError(
                message=f"Sandbox not found: {sandbox_id}",
                sandbox_id=sandbox_id,
                operation="call_tool",
            )

        last_error = None
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
                }

            except (SandboxConnectionError, ConnectionError) as e:
                last_error = e
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
                    break
            except Exception as e:
                # Non-retryable error
                logger.error(f"Tool call error: {e}")
                return {
                    "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                    "is_error": True,
                }
