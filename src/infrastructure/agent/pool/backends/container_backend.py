"""
Container Backend for HOT Tier.

Manages agent instances running in isolated Docker containers.
Each HOT tier project gets its own dedicated container with:
- Isolated resources (CPU, memory)
- Independent agent lifecycle
- gRPC communication

Features:
- Docker API integration for container management
- gRPC client for agent communication
- Automatic container health monitoring
- Resource limit enforcement
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ..config import AgentInstanceConfig
from ..instance import AgentInstance, ChatRequest
from ..types import (
    AgentInstanceStatus,
    HealthCheckResult,
    HealthStatus,
    ProjectTier,
)
from .base import Backend, BackendType

logger = logging.getLogger(__name__)


@dataclass
class ContainerInfo:
    """Container information."""

    container_id: str
    instance_key: str
    tenant_id: str
    project_id: str
    agent_mode: str
    grpc_endpoint: str
    health_endpoint: str
    status: str  # created, running, paused, stopped, error
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    started_at: datetime | None = None
    error_message: str | None = None
    resource_limits: dict[str, Any] = field(default_factory=dict)


@dataclass
class ContainerConfig:
    """Container backend configuration."""

    # Docker settings
    docker_host: str = "unix:///var/run/docker.sock"
    network_name: str = "memstack-agent-network"
    image_name: str = "memstack-agent-worker:latest"

    # Resource defaults for HOT tier
    default_memory_limit: str = "2g"
    default_cpu_limit: float = 2.0
    default_cpu_reservation: float = 0.5

    # Port allocation
    grpc_port_start: int = 50100
    health_port_start: int = 8100

    # Timeouts
    start_timeout_seconds: int = 60
    stop_timeout_seconds: int = 30
    health_check_interval_seconds: int = 10

    # Limits
    max_containers: int = 50


class ContainerBackend(Backend):
    """
    Container backend for HOT tier.

    Manages agent instances in isolated Docker containers with dedicated
    resources and gRPC communication.
    """

    def __init__(self, config: ContainerConfig | None = None) -> None:
        self._config = config or ContainerConfig()
        self._docker_client: Any | None = None
        self._containers: dict[str, ContainerInfo] = {}
        self._grpc_clients: dict[str, Any] = {}
        self._port_allocator: dict[str, int] = {}
        self._next_grpc_port = self._config.grpc_port_start
        self._next_health_port = self._config.health_port_start
        self._is_running = False
        self._health_task: asyncio.Task | None = None
        self._lock = asyncio.Lock()

    @property
    def backend_type(self) -> BackendType:
        return BackendType.CONTAINER

    async def start(self) -> None:
        """Start the container backend."""
        logger.info("Starting Container Backend")

        # Initialize Docker client
        try:
            import docker

            self._docker_client = docker.from_env()
            # Test connection
            self._docker_client.ping()
            logger.info(f"Docker client connected: {self._config.docker_host}")
        except ImportError:
            logger.error("Docker SDK not installed. Install with: pip install docker")
            raise RuntimeError("Docker SDK not available") from None
        except Exception as e:
            logger.error(f"Failed to connect to Docker: {e}")
            raise

        # Ensure network exists
        await self._ensure_network()

        # Start health monitoring
        self._is_running = True
        self._health_task = asyncio.create_task(self._health_monitor_loop())

        logger.info("Container Backend started")

    async def stop(self) -> None:
        """Stop the container backend."""
        logger.info("Stopping Container Backend")
        self._is_running = False

        # Stop health monitoring
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task

        # Stop all containers
        for instance_key in list(self._containers.keys()):
            try:
                await self.destroy_instance(instance_key, graceful=True)
            except Exception as e:
                logger.error(f"Error stopping container {instance_key}: {e}")

        # Close gRPC clients
        for client in self._grpc_clients.values():
            with contextlib.suppress(Exception):
                await client.close()
        self._grpc_clients.clear()

        logger.info("Container Backend stopped")

    async def create_instance(
        self,
        config: AgentInstanceConfig,
    ) -> AgentInstance:
        """Create a new container instance."""
        instance_key = f"{config.tenant_id}:{config.project_id}:{config.agent_mode}"

        async with self._lock:
            # Check if already exists
            if instance_key in self._containers:
                raise ValueError(f"Container already exists: {instance_key}")

            # Check container limit
            if len(self._containers) >= self._config.max_containers:
                raise RuntimeError(f"Container limit reached: {self._config.max_containers}")

            # Allocate ports
            grpc_port = self._next_grpc_port
            health_port = self._next_health_port
            self._next_grpc_port += 1
            self._next_health_port += 1

            try:
                # Create container
                container_info = await self._create_container(
                    config=config,
                    grpc_port=grpc_port,
                    health_port=health_port,
                )
                self._containers[instance_key] = container_info

                # Start container
                await self._start_container(container_info)

                # Wait for agent initialization
                await self._wait_for_ready(container_info)

                # Create AgentInstance wrapper
                instance = AgentInstance(
                    instance_key=instance_key,
                    tenant_id=config.tenant_id,
                    project_id=config.project_id,
                    agent_mode=config.agent_mode,
                    tier=ProjectTier.HOT,
                    config=config,
                )
                instance._status = AgentInstanceStatus.READY
                instance._is_initialized = True

                logger.info(
                    f"Created container instance: {instance_key}, "
                    f"container_id={container_info.container_id}"
                )
                return instance

            except Exception as e:
                logger.error(f"Failed to create container: {e}")
                # Cleanup on failure
                if instance_key in self._containers:
                    with contextlib.suppress(Exception):
                        await self._remove_container(self._containers[instance_key])
                    del self._containers[instance_key]
                raise

    async def destroy_instance(
        self,
        instance_id: str,
        graceful: bool = True,
    ) -> bool:
        """Destroy a container instance."""
        async with self._lock:
            if instance_id not in self._containers:
                return False

            container_info = self._containers[instance_id]

            try:
                # Send shutdown signal via gRPC
                if graceful:
                    try:
                        client = await self._get_grpc_client(instance_id)
                        await client.Shutdown(
                            graceful=True,
                            timeout_seconds=self._config.stop_timeout_seconds,
                        )
                    except Exception as e:
                        logger.warning(f"Failed to send shutdown signal: {e}")

                # Remove container
                await self._remove_container(container_info)

                # Cleanup
                del self._containers[instance_id]
                if instance_id in self._grpc_clients:
                    del self._grpc_clients[instance_id]

                logger.info(f"Destroyed container instance: {instance_id}")
                return True

            except Exception as e:
                logger.error(f"Error destroying container {instance_id}: {e}")
                return False

    async def get_instance(
        self,
        instance_id: str,
    ) -> AgentInstance | None:
        """Get an instance by ID."""
        if instance_id not in self._containers:
            return None

        container_info = self._containers[instance_id]

        # Get status from container
        status = await self._get_container_status(container_info)

        # Create AgentInstance representation
        instance = AgentInstance(
            instance_key=instance_id,
            tenant_id=container_info.tenant_id,
            project_id=container_info.project_id,
            agent_mode=container_info.agent_mode,
            tier=ProjectTier.HOT,
        )

        # Map container status to instance status
        if status == "running":
            instance._status = AgentInstanceStatus.READY
            instance._is_initialized = True
        elif status == "paused":
            instance._status = AgentInstanceStatus.PAUSED
        elif status == "error":
            instance._status = AgentInstanceStatus.UNHEALTHY
        else:
            instance._status = AgentInstanceStatus.CREATED

        return instance

    async def list_instances(self) -> list[AgentInstance]:
        """List all container instances."""
        instances = []
        for instance_id in self._containers:
            instance = await self.get_instance(instance_id)
            if instance:
                instances.append(instance)
        return instances

    async def execute(
        self,
        instance_id: str,
        request: ChatRequest,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute a request on a container instance."""
        if instance_id not in self._containers:
            yield {"event_type": "error", "error": {"message": "Instance not found"}}
            return

        try:
            client = await self._get_grpc_client(instance_id)

            # Execute via gRPC
            async for event in client.Execute(
                conversation_id=request.conversation_id,
                message=request.message,
                context=request.context,
            ):
                yield event

        except Exception as e:
            logger.error(f"Error executing on container {instance_id}: {e}")
            yield {"event_type": "error", "error": {"message": str(e)}}

    async def health_check(
        self,
        instance_id: str,
    ) -> HealthCheckResult:
        """Health check a container instance."""
        if instance_id not in self._containers:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message="Instance not found",
            )

        container_info = self._containers[instance_id]

        try:
            # Check container status
            container_status = await self._get_container_status(container_info)
            if container_status != "running":
                return HealthCheckResult(
                    status=HealthStatus.UNHEALTHY,
                    message=f"Container not running: {container_status}",
                )

            # Check agent health via HTTP
            import aiohttp

            async with aiohttp.ClientSession() as session:
                url = f"http://{container_info.health_endpoint}/health"
                async with session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        if data.get("status") == "healthy":
                            return HealthCheckResult(
                                status=HealthStatus.HEALTHY,
                                message="OK",
                                latency_ms=(time.time() - time.time()) * 1000,
                            )

            return HealthCheckResult(
                status=HealthStatus.DEGRADED,
                message="Health check failed",
            )

        except Exception as e:
            return HealthCheckResult(
                status=HealthStatus.UNHEALTHY,
                message=str(e),
            )

    def get_stats(self) -> dict[str, Any]:
        """Get backend statistics."""
        running = sum(1 for c in self._containers.values() if c.status == "running")
        return {
            "backend_type": self.backend_type.value,
            "total_containers": len(self._containers),
            "running_containers": running,
            "max_containers": self._config.max_containers,
            "is_running": self._is_running,
        }

    # =========================================================================
    # Private Methods - Docker Operations
    # =========================================================================

    async def _ensure_network(self) -> None:
        """Ensure Docker network exists."""
        if not self._docker_client:
            return

        try:
            self._docker_client.networks.get(self._config.network_name)
        except Exception:
            self._docker_client.networks.create(
                self._config.network_name,
                driver="bridge",
            )
            logger.info(f"Created Docker network: {self._config.network_name}")

    async def _create_container(
        self,
        config: AgentInstanceConfig,
        grpc_port: int,
        health_port: int,
    ) -> ContainerInfo:
        """Create a Docker container."""
        instance_key = f"{config.tenant_id}:{config.project_id}:{config.agent_mode}"
        container_name = f"agent-hot-{config.tenant_id}-{config.project_id}"[:63]

        # Resource limits
        memory_limit = config.resource_quota.memory_mb if config.resource_quota else 2048
        cpu_limit = config.resource_quota.cpu_cores if config.resource_quota else 2.0

        environment = {
            "AGENT_INSTANCE_ID": instance_key,
            "AGENT_TENANT_ID": config.tenant_id,
            "AGENT_PROJECT_ID": config.project_id,
            "AGENT_MODE": config.agent_mode,
            "GRPC_PORT": str(grpc_port),
            "HEALTH_PORT": str(health_port),
            "MAX_CONCURRENT_REQUESTS": str(
                config.resource_quota.max_concurrent if config.resource_quota else 50
            ),
            "MEMORY_LIMIT_MB": str(memory_limit),
            "LOG_LEVEL": "INFO",
        }

        # Create container (not started)
        container = self._docker_client.containers.create(
            image=self._config.image_name,
            name=container_name,
            environment=environment,
            ports={
                f"{grpc_port}/tcp": grpc_port,
                f"{health_port}/tcp": health_port,
            },
            mem_limit=f"{memory_limit}m",
            nano_cpus=int(cpu_limit * 1e9),
            network=self._config.network_name,
            detach=True,
            labels={
                "memstack.type": "agent-worker",
                "memstack.tier": "hot",
                "memstack.tenant": config.tenant_id,
                "memstack.project": config.project_id,
            },
        )

        return ContainerInfo(
            container_id=container.id,
            instance_key=instance_key,
            tenant_id=config.tenant_id,
            project_id=config.project_id,
            agent_mode=config.agent_mode,
            grpc_endpoint=f"localhost:{grpc_port}",
            health_endpoint=f"localhost:{health_port}",
            status="created",
            resource_limits={
                "memory_mb": memory_limit,
                "cpu_cores": cpu_limit,
            },
        )

    async def _start_container(self, container_info: ContainerInfo) -> None:
        """Start a container."""
        container = self._docker_client.containers.get(container_info.container_id)
        container.start()
        container_info.status = "running"
        container_info.started_at = datetime.now(UTC)
        logger.info(f"Started container: {container_info.container_id[:12]}")

    async def _remove_container(self, container_info: ContainerInfo) -> None:
        """Remove a container."""
        try:
            container = self._docker_client.containers.get(container_info.container_id)
            container.stop(timeout=self._config.stop_timeout_seconds)
            container.remove()
            logger.info(f"Removed container: {container_info.container_id[:12]}")
        except Exception as e:
            logger.warning(f"Error removing container: {e}")

    async def _get_container_status(self, container_info: ContainerInfo) -> str:
        """Get container status."""
        try:
            container = self._docker_client.containers.get(container_info.container_id)
            return container.status
        except Exception:
            return "error"

    async def _wait_for_ready(
        self,
        container_info: ContainerInfo,
        timeout: int = 60,
    ) -> None:
        """Wait for container agent to be ready."""
        import aiohttp

        start_time = time.time()
        url = f"http://{container_info.health_endpoint}/health"

        while time.time() - start_time < timeout:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, timeout=5) as response:
                        if response.status == 200:
                            data = await response.json()
                            if data.get("lifecycle_state") == "ready":
                                logger.info(f"Container ready: {container_info.container_id[:12]}")
                                return
            except Exception:
                pass

            await asyncio.sleep(1)

        raise TimeoutError(f"Container not ready after {timeout}s: {container_info.container_id}")

    async def _get_grpc_client(self, instance_id: str) -> None:
        """Get or create gRPC client for instance."""
        if instance_id in self._grpc_clients:
            return self._grpc_clients[instance_id]

        container_info = self._containers[instance_id]

        # Create a simple client wrapper that uses HTTP/JSON as fallback
        # (full gRPC implementation requires proto compilation)
        client = _HttpFallbackClient(
            health_endpoint=container_info.health_endpoint,
            grpc_endpoint=container_info.grpc_endpoint,
        )
        self._grpc_clients[instance_id] = client
        return client

    async def _health_monitor_loop(self) -> None:
        """Background health monitoring loop."""
        while self._is_running:
            try:
                for instance_id in list(self._containers.keys()):
                    result = await self.health_check(instance_id)
                    if result.status == HealthStatus.UNHEALTHY:
                        logger.warning(f"Container unhealthy: {instance_id}, {result.message}")
                        # Update container status
                        if instance_id in self._containers:
                            self._containers[instance_id].status = "error"
                            self._containers[instance_id].error_message = result.message

            except Exception as e:
                logger.error(f"Health monitor error: {e}")

            await asyncio.sleep(self._config.health_check_interval_seconds)


class _HttpFallbackClient:
    """HTTP fallback client when gRPC is not available."""

    def __init__(self, health_endpoint: str, grpc_endpoint: str) -> None:
        self.health_endpoint = health_endpoint
        self.grpc_endpoint = grpc_endpoint

    async def Shutdown(self, graceful: bool, timeout_seconds: int) -> dict[str, Any]:
        """Send shutdown via HTTP."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            url = f"http://{self.health_endpoint}/shutdown"
            async with session.post(
                url,
                json={"graceful": graceful, "timeout_seconds": timeout_seconds},
            ) as response:
                return await response.json()

    async def Execute(
        self,
        conversation_id: str,
        message: str,
        context: dict[str, str] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """Execute via HTTP streaming."""
        import aiohttp

        async with aiohttp.ClientSession() as session:
            url = f"http://{self.health_endpoint}/execute"
            async with session.post(
                url,
                json={
                    "conversation_id": conversation_id,
                    "message": message,
                    "context": context or {},
                },
            ) as response:
                async for line in response.content:
                    if line:
                        import json

                        yield json.loads(line.decode())

    async def close(self) -> None:
        """Close client."""
        pass
