"""
Container Manager - Docker container lifecycle management.

Handles creating, starting, stopping, and removing Docker containers
for sandbox environments. Extracted from MCPSandboxAdapter.
"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import docker
from docker.errors import ImageNotFound, NotFound
from docker.models.containers import Container

from src.infrastructure.adapters.secondary.sandbox.constants import (
    DEFAULT_SANDBOX_IMAGE,
    DESKTOP_PORT,
    MCP_WEBSOCKET_PORT,
    TERMINAL_PORT,
)
from src.infrastructure.adapters.secondary.sandbox.instance import (
    SandboxPorts,
)

logger = logging.getLogger(__name__)


class ContainerManager:
    """
    Manages Docker container lifecycle for sandbox environments.

    Responsibilities:
    - Creating containers with proper configuration
    - Starting, stopping, and removing containers
    - Port mapping and volume mounts
    - Container health checks
    - Cleanup of orphaned containers
    """

    def __init__(
        self,
        docker_client: docker.DockerClient,
        image: str = DEFAULT_SANDBOX_IMAGE,
        default_memory_limit: str = "2g",
        default_cpu_limit: str = "2",
        container_name_prefix: str = "memstack-sandbox",
    ):
        """
        Initialize container manager.

        Args:
            docker_client: Docker client instance
            image: Default Docker image for sandboxes
            default_memory_limit: Default memory limit (e.g., "2g")
            default_cpu_limit: Default CPU limit
            container_name_prefix: Prefix for container names
        """
        self._docker = docker_client
        self._image = image
        self._default_memory_limit = default_memory_limit
        self._default_cpu_limit = default_cpu_limit
        self._container_name_prefix = container_name_prefix

    def _generate_container_name(self, sandbox_id: str) -> str:
        """Generate unique container name."""
        short_id = sandbox_id[:8] if len(sandbox_id) > 8 else sandbox_id
        return f"{self._container_name_prefix}-{short_id}"

    async def create_container(
        self,
        sandbox_id: str,
        project_path: str,
        ports: SandboxPorts,
        memory_limit: Optional[str] = None,
        cpu_limit: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        project_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> Container:
        """
        Create a new Docker container for sandbox.

        Args:
            sandbox_id: Unique sandbox identifier
            project_path: Host path to mount as project directory
            ports: Port allocation for services
            memory_limit: Memory limit override
            cpu_limit: CPU limit override
            environment: Additional environment variables
            project_id: Project ID for labeling
            tenant_id: Tenant ID for labeling

        Returns:
            Created Docker container

        Raises:
            Exception: If container creation fails
        """
        container_name = self._generate_container_name(sandbox_id)

        # Ensure image exists
        await self._ensure_image_exists()

        # Build port bindings
        port_bindings = {
            f"{MCP_WEBSOCKET_PORT}/tcp": ("0.0.0.0", ports.mcp_port),
            f"{DESKTOP_PORT}/tcp": ("0.0.0.0", ports.desktop_port),
            f"{TERMINAL_PORT}/tcp": ("0.0.0.0", ports.terminal_port),
        }

        # Build environment
        env = {
            "SANDBOX_ID": sandbox_id,
            "PROJECT_ID": project_id or "",
            "TENANT_ID": tenant_id or "",
            **(environment or {}),
        }

        # Build labels
        labels = {
            "memstack.sandbox": "true",
            "memstack.sandbox.id": sandbox_id,
            "memstack.project.id": project_id or "",
            "memstack.tenant.id": tenant_id or "",
            "memstack.created_at": datetime.now().isoformat(),
        }

        # Build volume mounts
        volumes = {
            project_path: {"bind": "/workspace", "mode": "rw"},
        }

        # Resource limits
        mem_limit = memory_limit or self._default_memory_limit
        cpu_count = int(cpu_limit or self._default_cpu_limit)

        logger.info(
            f"Creating container {container_name} "
            f"(MCP:{ports.mcp_port}, Desktop:{ports.desktop_port}, Terminal:{ports.terminal_port})"
        )

        # Create container in executor to avoid blocking
        loop = asyncio.get_event_loop()
        container = await loop.run_in_executor(
            None,
            lambda: self._docker.containers.create(
                image=self._image,
                name=container_name,
                ports=port_bindings,
                environment=env,
                labels=labels,
                volumes=volumes,
                mem_limit=mem_limit,
                nano_cpus=cpu_count * 1_000_000_000,
                detach=True,
                tty=True,
                stdin_open=True,
            ),
        )

        logger.info(f"Created container {container.id[:12]} for sandbox {sandbox_id}")
        return container

    async def start_container(self, container: Container) -> None:
        """Start a container."""
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, container.start)
        logger.info(f"Started container {container.id[:12]}")

    async def stop_container(
        self,
        container: Container,
        timeout: int = 10,
    ) -> None:
        """Stop a container gracefully."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: container.stop(timeout=timeout))
            logger.info(f"Stopped container {container.id[:12]}")
        except Exception as e:
            logger.warning(f"Error stopping container {container.id[:12]}: {e}")

    async def remove_container(
        self,
        container: Container,
        force: bool = True,
        v: bool = True,
    ) -> None:
        """Remove a container."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: container.remove(force=force, v=v))
            logger.info(f"Removed container {container.id[:12]}")
        except NotFound:
            logger.debug(f"Container {container.id[:12]} already removed")
        except Exception as e:
            logger.warning(f"Error removing container {container.id[:12]}: {e}")

    async def get_container(self, container_id: str) -> Optional[Container]:
        """Get container by ID."""
        loop = asyncio.get_event_loop()
        try:
            return await loop.run_in_executor(
                None, lambda: self._docker.containers.get(container_id)
            )
        except NotFound:
            return None
        except Exception as e:
            logger.error(f"Error getting container {container_id}: {e}")
            return None

    async def get_container_by_sandbox_id(self, sandbox_id: str) -> Optional[Container]:
        """Get container by sandbox ID label."""
        loop = asyncio.get_event_loop()
        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(
                    all=True,
                    filters={"label": f"memstack.sandbox.id={sandbox_id}"},
                ),
            )
            return containers[0] if containers else None
        except Exception as e:
            logger.error(f"Error finding container for sandbox {sandbox_id}: {e}")
            return None

    async def container_exists(self, sandbox_id: str) -> bool:
        """Check if container exists for sandbox."""
        container = await self.get_container_by_sandbox_id(sandbox_id)
        return container is not None

    async def is_container_running(self, container: Container) -> bool:
        """Check if container is running."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, container.reload)
            return container.status == "running"
        except Exception:
            return False

    async def list_sandbox_containers(
        self,
        project_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> List[Container]:
        """List all sandbox containers with optional filtering."""
        loop = asyncio.get_event_loop()
        filters = {"label": "memstack.sandbox=true"}

        if project_id:
            filters["label"] = [
                "memstack.sandbox=true",
                f"memstack.project.id={project_id}",
            ]

        try:
            containers = await loop.run_in_executor(
                None,
                lambda: self._docker.containers.list(all=True, filters=filters),
            )

            # Filter by tenant if specified
            if tenant_id:
                containers = [
                    c
                    for c in containers
                    if c.labels.get("memstack.tenant.id") == tenant_id
                ]

            return containers
        except Exception as e:
            logger.error(f"Error listing sandbox containers: {e}")
            return []

    async def cleanup_orphaned_containers(self) -> int:
        """Remove orphaned sandbox containers."""
        count = 0
        containers = await self.list_sandbox_containers()

        for container in containers:
            # Check if container is in a bad state
            if container.status in ("exited", "dead", "created"):
                try:
                    await self.remove_container(container)
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to cleanup container {container.id[:12]}: {e}")

        if count > 0:
            logger.info(f"Cleaned up {count} orphaned containers")

        return count

    async def get_container_stats(self, container: Container) -> Dict[str, Any]:
        """Get resource usage stats for container."""
        loop = asyncio.get_event_loop()
        try:
            stats = await loop.run_in_executor(
                None, lambda: container.stats(stream=False)
            )

            # Parse CPU usage
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

            # Parse memory usage
            memory_usage = stats["memory_stats"].get("usage", 0)
            memory_limit = stats["memory_stats"].get("limit", 1)
            memory_mb = memory_usage / (1024 * 1024)

            return {
                "cpu_percent": cpu_percent,
                "memory_mb": memory_mb,
                "memory_limit_mb": memory_limit / (1024 * 1024),
                "memory_percent": (memory_usage / memory_limit) * 100 if memory_limit else 0,
            }
        except Exception as e:
            logger.error(f"Error getting container stats: {e}")
            return {}

    async def _ensure_image_exists(self) -> None:
        """Ensure Docker image exists, pull if needed."""
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(
                None, lambda: self._docker.images.get(self._image)
            )
        except ImageNotFound:
            logger.info(f"Pulling image {self._image}...")
            await loop.run_in_executor(
                None, lambda: self._docker.images.pull(self._image)
            )
            logger.info(f"Successfully pulled image {self._image}")
