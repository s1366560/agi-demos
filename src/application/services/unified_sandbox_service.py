"""Unified Sandbox Service - Single entry point for sandbox operations.

This service implements the SandboxResourcePort interface, providing a clean
abstraction for agent workflow to access sandbox functionality without coupling
to specific implementation details.

Core Principles:
1. Each project has exactly one persistent sandbox
2. Lazy creation on first access
3. Health monitoring and auto-recovery
4. Agent-friendly interface (no direct Docker/adapter access)

Implements: SandboxResourcePort
"""

import asyncio
import base64
import logging
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.exc import IntegrityError

from src.application.services.sandbox_profile import SandboxProfileType
from src.application.services.sandbox_profile import get_profile as get_sandbox_profile
from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
    SandboxType,
)
from src.domain.ports.repositories.project_sandbox_repository import (
    ProjectSandboxRepository,
)
from src.domain.ports.services.distributed_lock_port import DistributedLockPort
from src.domain.ports.services.sandbox_resource_port import (
    SandboxResourcePort,
    SandboxInfo,
)
from src.domain.ports.services.sandbox_port import (
    SandboxConfig,
    SandboxNotFoundError,
    SandboxStatus,
)
from src.infrastructure.adapters.secondary.sandbox.constants import DEFAULT_SANDBOX_IMAGE

logger = logging.getLogger(__name__)


# Re-export SandboxInfo from domain layer for convenience
__all__ = ["UnifiedSandboxService"]


class UnifiedSandboxService(SandboxResourcePort):
    """Unified service for managing project sandbox lifecycles.

    This service provides a single entry point for all sandbox operations,
    combining the best of ProjectSandboxLifecycleService and SandboxManagerService.

    Usage:
        service = UnifiedSandboxService(repository, adapter, lock)

        # Get or create (lazy initialization)
        info = await service.get_or_create("proj-123", "tenant-456")

        # Execute tools
        result = await service.execute_tool(
            "proj-123", "bash", {"command": "ls -la"}
        )

        # Restart if needed
        await service.restart("proj-123")

        # Terminate when done
        await service.terminate("proj-123")
    """

    def __init__(
        self,
        repository: ProjectSandboxRepository,
        sandbox_adapter: Any,  # MCPSandboxAdapter or compatible
        distributed_lock: Optional[DistributedLockPort] = None,
        default_profile: SandboxProfileType = SandboxProfileType.STANDARD,
        health_check_interval_seconds: int = 60,
        auto_recover: bool = True,
    ):
        """Initialize the unified sandbox service.

        Args:
            repository: Repository for ProjectSandbox associations
            sandbox_adapter: Adapter for sandbox container operations
            distributed_lock: Distributed lock for cross-process safety
            default_profile: Default sandbox profile
            health_check_interval_seconds: Minimum seconds between health checks
            auto_recover: Whether to auto-recover unhealthy sandboxes
        """
        self._repository = repository
        self._adapter = sandbox_adapter
        self._distributed_lock = distributed_lock
        self._default_profile = default_profile
        self._health_check_interval = health_check_interval_seconds
        self._auto_recover = auto_recover

        # Per-project locks for in-process concurrency control
        self._project_locks: Dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()

    async def _get_project_lock(self, project_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific project."""
        async with self._locks_lock:
            if project_id not in self._project_locks:
                self._project_locks[project_id] = asyncio.Lock()
            return self._project_locks[project_id]

    async def _cleanup_project_lock(self, project_id: str) -> None:
        """Clean up the lock for a project."""
        async with self._locks_lock:
            self._project_locks.pop(project_id, None)

    # -------------------------------------------------------------------------
    # Core API Methods (6 methods)
    # -------------------------------------------------------------------------

    async def get_or_create(
        self,
        project_id: str,
        tenant_id: str,
        profile: Optional[SandboxProfileType] = None,
        config_override: Optional[Dict[str, Any]] = None,
        max_retries: int = 3,
    ) -> SandboxInfo:
        """Get existing sandbox or create a new one for the project.

        This is the primary method for accessing project sandboxes. It ensures
        that each project has exactly one persistent sandbox.

        Thread Safety:
            - Database-level: Unique constraint on project_id
            - Distributed: Redis lock for cross-process safety
            - In-process: asyncio.Lock for same-worker concurrency

        Args:
            project_id: The project ID
            tenant_id: The tenant ID
            profile: Sandbox profile (lite, standard, full)
            config_override: Optional configuration overrides
            max_retries: Maximum retries on constraint violation

        Returns:
            SandboxInfo with connection details and status
        """
        for attempt in range(max_retries):
            try:
                return await self._get_or_create_impl(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    profile=profile,
                    config_override=config_override,
                )
            except IntegrityError:
                logger.info(
                    f"Concurrent creation detected for project {project_id} "
                    f"(attempt {attempt + 1}/{max_retries}), retrying..."
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.2 * (attempt + 1))
                    continue
                # Final attempt - try to return existing
                existing = await self._repository.find_by_project(project_id)
                if existing:
                    return await self._build_sandbox_info(existing)
                raise RuntimeError(
                    f"Failed to create sandbox for project {project_id} "
                    f"after {max_retries} attempts"
                )

        raise RuntimeError(f"Unexpected state in get_or_create for {project_id}")

    async def execute_tool(
        self,
        project_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
        """Execute a tool in the project's sandbox.

        Automatically ensures the sandbox is running before execution.

        Args:
            project_id: The project ID
            tool_name: MCP tool name (bash, read, write, etc.)
            arguments: Tool arguments
            timeout: Execution timeout in seconds

        Returns:
            Tool execution result

        Raises:
            SandboxNotFoundError: If no sandbox exists for the project
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            raise SandboxNotFoundError(
                message=f"No sandbox found for project {project_id}",
                sandbox_id=project_id,
                operation="execute_tool",
            )

        # Update access time
        association.mark_accessed()
        await self._repository.save(association)

        # Execute tool via adapter
        return await self._adapter.call_tool(
            sandbox_id=association.sandbox_id,
            tool_name=tool_name,
            arguments=arguments,
            timeout=timeout,
        )

    async def restart(self, project_id: str) -> SandboxInfo:
        """Restart the sandbox for a project.

        Creates a new container while preserving the sandbox_id for
        tool cache compatibility.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo for the restarted sandbox

        Raises:
            SandboxNotFoundError: If no sandbox exists for the project
        """
        project_lock = await self._get_project_lock(project_id)
        async with project_lock:
            association = await self._repository.find_by_project(project_id)
            if not association:
                raise SandboxNotFoundError(
                    message=f"No sandbox found for project {project_id}",
                    project_id=project_id,
                )
            return await self._recreate_sandbox(association)

    async def terminate(
        self,
        project_id: str,
        delete_association: bool = True,
    ) -> bool:
        """Terminate the sandbox for a project.

        Args:
            project_id: The project ID
            delete_association: Whether to delete the association record

        Returns:
            True if terminated successfully, False otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            logger.warning(f"No sandbox association found for project {project_id}")
            return False

        try:
            # Terminate the sandbox container
            await self._adapter.terminate_sandbox(association.sandbox_id)

            # Update association status
            association.mark_terminated()
            await self._repository.save(association)

            # Optionally delete the association
            if delete_association:
                await self._repository.delete(association.id)

            # Clean up project lock
            await self._cleanup_project_lock(project_id)

            logger.info(f"Terminated sandbox for project {project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to terminate sandbox for project {project_id}: {e}")
            return False

    async def get_status(self, project_id: str) -> Optional[SandboxInfo]:
        """Get sandbox status for a project.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo if sandbox exists, None otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return None

        return await self._build_sandbox_info(association)

    async def health_check(self, project_id: str) -> bool:
        """Perform health check on project's sandbox.

        Args:
            project_id: The project ID

        Returns:
            True if healthy, False otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return False

        # Check if health check is needed
        if not association.needs_health_check(self._health_check_interval):
            return association.is_usable()

        # Perform health check via adapter
        try:
            healthy = await self._adapter.health_check(association.sandbox_id)

            if healthy:
                association.mark_healthy()
            else:
                association.mark_unhealthy("Health check failed")

            await self._repository.save(association)
            return healthy

        except Exception as e:
            logger.error(f"Health check error for project {project_id}: {e}")
            association.mark_unhealthy(str(e))
            await self._repository.save(association)
            return False

    # -------------------------------------------------------------------------
    # SandboxResourcePort Interface Implementation
    # -------------------------------------------------------------------------

    async def get_sandbox_id(
        self,
        project_id: str,
        tenant_id: str,
    ) -> Optional[str]:
        """Get the sandbox ID for a project without creating one.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            The sandbox ID if one exists, None otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return None

        # Check if sandbox is actually usable
        if association.is_usable():
            container_exists = await self._adapter.container_exists(
                association.sandbox_id
            )
            if container_exists:
                return association.sandbox_id

        return None

    async def ensure_sandbox_ready(
        self,
        project_id: str,
        tenant_id: str,
    ) -> str:
        """Ensure a sandbox is ready for the project, creating if necessary.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            The sandbox ID that is ready for use

        Raises:
            SandboxNotFoundError: If sandbox creation fails
        """
        info = await self.get_or_create(
            project_id=project_id,
            tenant_id=tenant_id,
        )
        return info.sandbox_id

    async def sync_file(
        self,
        project_id: str,
        filename: str,
        content_base64: str,
        destination: str = "/workspace",
    ) -> bool:
        """Sync a file to the project's sandbox.

        This method decodes the base64 content and writes it to the sandbox.

        Args:
            project_id: The project ID
            filename: The name of the file
            content_base64: Base64-encoded file content
            destination: Target directory in sandbox

        Returns:
            True if sync succeeded, False otherwise
        """
        try:
            # Decode base64 content
            content_bytes = base64.b64decode(content_base64)
            content_str = content_bytes.decode("utf-8")

            # Get tenant_id from association
            association = await self._repository.find_by_project(project_id)
            if not association:
                logger.warning(f"No sandbox found for project {project_id}")
                return False

            # Ensure sandbox exists
            sandbox_id = await self.ensure_sandbox_ready(
                project_id=project_id,
                tenant_id=association.tenant_id,
            )

            # Use the write tool to sync the file
            result = await self._adapter.call_tool(
                sandbox_id=sandbox_id,
                tool_name="write",
                arguments={
                    "file_path": f"{destination}/{filename}",
                    "content": content_str,
                },
                timeout=30.0,
            )

            # Check if write succeeded
            if result.get("error"):
                logger.error(
                    f"Failed to sync file {filename} to sandbox {sandbox_id}: "
                    f"{result.get('error')}"
                )
                return False

            logger.debug(
                f"Synced file {filename} to sandbox {sandbox_id} "
                f"({len(content_bytes)} bytes)"
            )
            return True

        except Exception as e:
            logger.error(f"Error syncing file {filename} to project {project_id}: {e}")
            return False

    async def get_sandbox_info(
        self,
        project_id: str,
    ) -> Optional[SandboxInfo]:
        """Get information about the project's sandbox.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo if sandbox exists, None otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return None

        return await self._build_sandbox_info(association)

    # -------------------------------------------------------------------------
    # Private helper methods
    # -------------------------------------------------------------------------

    async def _get_or_create_impl(
        self,
        project_id: str,
        tenant_id: str,
        profile: Optional[SandboxProfileType] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> SandboxInfo:
        """Internal implementation with multi-layer locking."""
        project_lock = await self._get_project_lock(project_id)

        async with project_lock:
            # Try to acquire distributed lock
            lock_key = f"sandbox:create:{project_id}"
            lock_handle = None
            use_redis_lock = self._distributed_lock is not None

            try:
                if use_redis_lock:
                    lock_handle = await self._distributed_lock.acquire(
                        key=lock_key,
                        ttl=120,
                        blocking=True,
                        timeout=30.0,
                    )
                    db_lock_acquired = lock_handle is not None
                else:
                    db_lock_acquired = await self._repository.acquire_project_lock(
                        project_id, blocking=True, timeout_seconds=30
                    )

                if not db_lock_acquired:
                    # Another process is creating, wait and check
                    await asyncio.sleep(1.0)
                    existing = await self._repository.find_by_project(project_id)
                    if existing and existing.is_usable():
                        existing.mark_accessed()
                        await self._repository.save(existing)
                        return await self._build_sandbox_info(existing)
                    raise IntegrityError(
                        statement="distributed_lock",
                        params={},
                        orig=Exception("Could not acquire distributed lock"),
                    )

                # Double-check after acquiring lock
                existing = await self._repository.find_by_project(project_id)

                if existing:
                    if existing.is_usable():
                        container_exists = await self._adapter.container_exists(
                            existing.sandbox_id
                        )
                        if container_exists:
                            existing.mark_accessed()
                            await self._repository.save(existing)
                            return await self._build_sandbox_info(existing)
                        else:
                            # Container was killed externally, clean up and recreate
                            await self._cleanup_failed_sandbox(existing)

                    elif existing.status == ProjectSandboxStatus.ERROR:
                        await self._cleanup_failed_sandbox(existing)

                # Create new sandbox
                return await self._create_new_sandbox(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    profile=profile,
                    config_override=config_override,
                )
            finally:
                if use_redis_lock and lock_handle:
                    await self._distributed_lock.release(lock_handle)
                elif not use_redis_lock:
                    await self._repository.release_project_lock(project_id)

    async def _create_new_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        profile: Optional[SandboxProfileType] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> SandboxInfo:
        """Create a new sandbox for a project."""
        sandbox_id = f"proj-sb-{uuid.uuid4().hex[:12]}"
        project_path = f"/tmp/memstack_{project_id}"

        # Create association record
        association = ProjectSandbox(
            id=str(uuid.uuid4()),
            project_id=project_id,
            tenant_id=tenant_id,
            sandbox_id=sandbox_id,
            status=ProjectSandboxStatus.CREATING,
        )
        await self._repository.save(association)

        try:
            config = self._resolve_config(profile, config_override)

            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
                project_id=project_id,
                tenant_id=tenant_id,
            )

            association.sandbox_id = instance.id
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.now(timezone.utc)
            association.mark_healthy()
            await self._repository.save(association)

            # Connect MCP
            try:
                await self._adapter.connect_mcp(instance.id)
            except Exception as e:
                logger.warning(f"Failed to connect MCP for {instance.id}: {e}")

            logger.info(f"Created sandbox {instance.id} for project {project_id}")
            return await self._build_sandbox_info(association)

        except Exception as e:
            logger.error(f"Failed to create sandbox for project {project_id}: {e}")
            association.mark_error(str(e))
            await self._repository.save(association)
            raise

    async def _recreate_sandbox(self, association: ProjectSandbox) -> SandboxInfo:
        """Recreate a sandbox while preserving the sandbox_id."""
        project_path = f"/tmp/memstack_{association.project_id}"
        original_sandbox_id = association.sandbox_id

        # Clean up existing containers
        try:
            await self._adapter.terminate_sandbox(original_sandbox_id)
        except Exception:
            pass

        try:
            await self._adapter.cleanup_project_containers(association.project_id)
        except Exception as e:
            logger.warning(f"Failed to cleanup project containers: {e}")

        association.status = ProjectSandboxStatus.CREATING
        association.error_message = None
        await self._repository.save(association)

        try:
            config = self._resolve_config(self._default_profile, None)
            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
                project_id=association.project_id,
                tenant_id=association.tenant_id,
                sandbox_id=original_sandbox_id,  # Preserve for tool compatibility
            )

            association.sandbox_id = instance.id
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.now(timezone.utc)
            association.mark_healthy()
            await self._repository.save(association)

            try:
                await self._adapter.connect_mcp(instance.id)
            except Exception as e:
                logger.warning(f"Failed to connect MCP for {instance.id}: {e}")

            logger.info(
                f"Recreated sandbox for project {association.project_id}: "
                f"sandbox_id={instance.id}"
            )
            return await self._build_sandbox_info(association)

        except Exception as e:
            logger.error(f"Failed to recreate sandbox: {e}")
            association.mark_error(f"Recreation failed: {e}")
            await self._repository.save(association)
            raise

    async def _cleanup_failed_sandbox(self, association: ProjectSandbox) -> None:
        """Clean up a failed sandbox before recreating."""
        try:
            await self._adapter.terminate_sandbox(association.sandbox_id)
        except Exception:
            pass

        try:
            await self._adapter.cleanup_project_containers(association.project_id)
        except Exception as e:
            logger.warning(
                f"Failed to cleanup orphan containers for project {association.project_id}: {e}"
            )

        try:
            await self._repository.delete(association.id)
            logger.info(
                f"Deleted sandbox association {association.id} "
                f"for project {association.project_id}"
            )
        except Exception as e:
            logger.error(f"Failed to delete sandbox association {association.id}: {e}")

    async def _build_sandbox_info(self, association: ProjectSandbox) -> SandboxInfo:
        """Build SandboxInfo from association and container.

        This method now includes the list of available tools from the sandbox,
        eliminating the need for a separate SandboxToolRegistry service.
        """
        instance = await self._adapter.get_sandbox(association.sandbox_id)

        is_healthy = (
            association.status == ProjectSandboxStatus.RUNNING
            and instance is not None
            and instance.status == SandboxStatus.RUNNING
        )

        # Fetch available tools from sandbox (if healthy and MCP is connected)
        available_tools: List[str] = []
        if is_healthy and hasattr(self._adapter, "list_tools"):
            try:
                tool_list = await self._adapter.list_tools(association.sandbox_id)
                available_tools = [t.get("name", t) for t in tool_list if isinstance(t, dict)]
                if not available_tools and isinstance(tool_list, list):
                    # Fallback: tool_list might be list of strings
                    available_tools = [str(t) for t in tool_list]
            except Exception as e:
                logger.debug(
                    f"Failed to fetch tools for {association.sandbox_id}: {e}"
                )

        return SandboxInfo(
            sandbox_id=association.sandbox_id,
            project_id=association.project_id,
            tenant_id=association.tenant_id,
            status=association.status.value,
            endpoint=getattr(instance, "endpoint", None) if instance else None,
            websocket_url=getattr(instance, "websocket_url", None) if instance else None,
            mcp_port=getattr(instance, "mcp_port", None) if instance else None,
            desktop_port=getattr(instance, "desktop_port", None) if instance else None,
            terminal_port=getattr(instance, "terminal_port", None) if instance else None,
            desktop_url=getattr(instance, "desktop_url", None) if instance else None,
            terminal_url=getattr(instance, "terminal_url", None) if instance else None,
            created_at=association.created_at,
            last_accessed_at=association.last_accessed_at,
            is_healthy=is_healthy,
            error_message=association.error_message,
            available_tools=available_tools,
        )

    def _resolve_config(
        self,
        profile: Optional[SandboxProfileType],
        config_override: Optional[Dict[str, Any]],
    ) -> SandboxConfig:
        """Resolve sandbox configuration from profile and overrides."""
        profile_type = profile or self._default_profile
        sandbox_profile = get_sandbox_profile(profile_type)

        image = sandbox_profile.image_name or DEFAULT_SANDBOX_IMAGE

        config = SandboxConfig(
            image=image,
            memory_limit=sandbox_profile.memory_limit,
            cpu_limit=sandbox_profile.cpu_limit,
            timeout_seconds=sandbox_profile.timeout_seconds,
            desktop_enabled=sandbox_profile.desktop_enabled,
            environment=config_override.get("environment") if config_override else {},
        )

        if config_override:
            if "image" in config_override:
                config.image = config_override["image"]
            if "memory_limit" in config_override:
                config.memory_limit = config_override["memory_limit"]
            if "cpu_limit" in config_override:
                config.cpu_limit = config_override["cpu_limit"]
            if "timeout_seconds" in config_override:
                config.timeout_seconds = config_override["timeout_seconds"]
            if "desktop_enabled" in config_override:
                config.desktop_enabled = config_override["desktop_enabled"]

        return config
