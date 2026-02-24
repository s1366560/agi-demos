"""Project Sandbox Lifecycle Service.

Manages the lifecycle of project-dedicated sandboxes:
- Each project has exactly one persistent sandbox
- Lazy creation on first use
- Health monitoring and auto-recovery
- Resource cleanup on project deletion

Threading Safety:
- Uses Redis distributed locks for cross-process safety (primary)
- Falls back to PostgreSQL advisory locks if Redis unavailable
- In-process locks for additional protection within single worker
- Handles unique constraint violations with retry mechanism
"""

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy.exc import IntegrityError

from src.application.services.sandbox_profile import (
    SandboxProfileType,
    get_profile as get_sandbox_profile,
)
from src.domain.model.sandbox.exceptions import SandboxLockTimeoutError
from src.domain.model.sandbox.project_sandbox import ProjectSandbox, ProjectSandboxStatus
from src.domain.ports.repositories.project_sandbox_repository import ProjectSandboxRepository
from src.domain.ports.services.distributed_lock_port import DistributedLockPort
from src.domain.ports.services.sandbox_port import (
    SandboxConfig,
    SandboxNotFoundError,
    SandboxStatus,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

logger = logging.getLogger(__name__)


@dataclass
class SandboxInfo:
    """Information about a project's sandbox."""

    sandbox_id: str
    project_id: str
    tenant_id: str
    status: str
    endpoint: str | None = None
    websocket_url: str | None = None
    mcp_port: int | None = None
    desktop_port: int | None = None
    terminal_port: int | None = None
    desktop_url: str | None = None
    terminal_url: str | None = None
    created_at: datetime | None = None
    last_accessed_at: datetime | None = None
    is_healthy: bool = False
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "sandbox_id": self.sandbox_id,
            "project_id": self.project_id,
            "tenant_id": self.tenant_id,
            "status": self.status,
            "endpoint": self.endpoint,
            "websocket_url": self.websocket_url,
            "mcp_port": self.mcp_port,
            "desktop_port": self.desktop_port,
            "terminal_port": self.terminal_port,
            "desktop_url": self.desktop_url,
            "terminal_url": self.terminal_url,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_accessed_at": self.last_accessed_at.isoformat()
            if self.last_accessed_at
            else None,
            "is_healthy": self.is_healthy,
            "error_message": self.error_message,
        }


class ProjectSandboxLifecycleService:
    """Service for managing project-dedicated sandbox lifecycles.

    This service ensures each project has exactly one persistent sandbox that:
    1. Is created lazily on first use
    2. Remains running for the lifetime of the project
    3. Is health-monitored and auto-recovered if unhealthy
    4. Can be accessed via project_id without managing sandbox_id

    Usage:
        service = ProjectSandboxLifecycleService(repository, adapter)

        # Get or create sandbox for a project
        sandbox_info = await service.get_or_create_sandbox(
            project_id="proj-123",
            tenant_id="tenant-456",
        )

        # Access sandbox operations via project_id
        result = await service.execute_tool(
            project_id="proj-123",
            tool_name="bash",
            arguments={"command": "ls -la"},
        )

        # Terminate project's sandbox
        await service.terminate_project_sandbox("proj-123")
    """

    def __init__(
        self,
        repository: ProjectSandboxRepository,
        sandbox_adapter: MCPSandboxAdapter,
        distributed_lock: DistributedLockPort | None = None,
        default_profile: SandboxProfileType = SandboxProfileType.STANDARD,
        health_check_interval_seconds: int = 60,
        auto_recover: bool = True,
        memory_limit_override: str | None = None,
        cpu_limit_override: str | None = None,
    ) -> None:
        """Initialize the lifecycle service.

        Args:
            repository: Repository for ProjectSandbox associations
            sandbox_adapter: Adapter for sandbox container operations
            distributed_lock: Distributed lock for cross-process safety (optional)
                            If not provided, falls back to PostgreSQL advisory locks
            default_profile: Default sandbox profile
            health_check_interval_seconds: Minimum seconds between health checks
            auto_recover: Whether to auto-recover unhealthy sandboxes
            memory_limit_override: Override for memory limit (e.g. from config)
            cpu_limit_override: Override for CPU limit (e.g. from config)
        """
        self._repository = repository
        self._adapter = sandbox_adapter
        self._distributed_lock = distributed_lock
        self._default_profile = default_profile
        self._health_check_interval = health_check_interval_seconds
        self._auto_recover = auto_recover
        self._memory_limit_override = memory_limit_override
        self._cpu_limit_override = cpu_limit_override
        self._background_tasks: set[asyncio.Task[Any]] = set()

        # Per-project locks to prevent concurrent sandbox creation for the same project
        # This ensures exactly one sandbox per project even under high concurrency
        self._project_locks: dict[str, asyncio.Lock] = {}
        self._locks_lock = asyncio.Lock()  # Lock for accessing _project_locks

    async def _get_project_lock(self, project_id: str) -> asyncio.Lock:
        """Get or create a lock for a specific project.

        Args:
            project_id: The project ID

        Returns:
            asyncio.Lock for the project
        """
        async with self._locks_lock:
            if project_id not in self._project_locks:
                self._project_locks[project_id] = asyncio.Lock()
            return self._project_locks[project_id]

    async def _cleanup_project_lock(self, project_id: str) -> None:
        """Clean up the lock for a project (call after sandbox is terminated).

        Args:
            project_id: The project ID
        """
        async with self._locks_lock:
            self._project_locks.pop(project_id, None)

    async def get_or_create_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        profile: SandboxProfileType | None = None,
        config_override: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> SandboxInfo:
        """Get existing sandbox or create a new one for the project.

        This is the primary method for accessing project sandboxes. It ensures
        that each project has exactly one persistent sandbox.

        Thread Safety (Multi-Layer Protection):
            1. Database-level: PostgreSQL advisory lock for cross-process safety
            2. In-process: asyncio.Lock for same-process concurrency
            3. Database constraint: Unique constraint on project_id with retry

        Args:
            project_id: The project ID
            tenant_id: The tenant ID for scoping
            profile: Sandbox profile (lite, standard, full)
            config_override: Optional configuration overrides
            max_retries: Maximum retries on constraint violation

        Returns:
            SandboxInfo with connection details and status

        Raises:
            SandboxError: If sandbox creation fails after all retries
        """
        for attempt in range(max_retries):
            try:
                return await self._get_or_create_sandbox_impl(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    profile=profile,
                    config_override=config_override,
                )
            except (IntegrityError, SandboxLockTimeoutError) as e:
                # Unique constraint violation or lock timeout - retry
                logger.info(
                    f"Concurrent sandbox creation detected for project {project_id} "
                    f"(attempt {attempt + 1}/{max_retries}), retrying..."
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(0.2 * (2**attempt))
                    continue
                # Final attempt failed, try to return existing
                existing = await self._repository.find_by_project(project_id)
                if existing:
                    return await self._get_sandbox_info(existing)
                raise RuntimeError(
                    f"Failed to create sandbox for project {project_id} after {max_retries} attempts: {e}"
                ) from e

        # Should not reach here, but just in case
        raise RuntimeError(f"Unexpected state in get_or_create_sandbox for project {project_id}")

    async def _get_or_create_sandbox_impl(
        self,
        project_id: str,
        tenant_id: str,
        profile: SandboxProfileType | None = None,
        config_override: dict[str, Any] | None = None,
    ) -> SandboxInfo:
        """Internal implementation of get_or_create_sandbox with multi-layer locking.

        Uses:
        1. In-process asyncio.Lock (fast path for same-worker concurrency)
        2. Redis distributed lock (primary, cross-process safety)
        3. Fallback to PostgreSQL advisory lock if Redis unavailable

        CRITICAL: The distributed lock is held until container creation completes to prevent
        any other process from creating a container for the same project.
        """
        # Layer 1: In-process lock (fast path for same-worker concurrency)
        project_lock = await self._get_project_lock(project_id)

        async with project_lock:
            # Layer 2: Distributed lock (Redis primary, PostgreSQL fallback)
            # This lock persists until explicitly released, NOT until transaction ends
            lock_key = f"sandbox:create:{project_id}"
            lock_handle = None
            use_redis_lock = self._distributed_lock is not None

            try:
                lock_handle, db_lock_acquired = await self._acquire_distributed_lock(
                    lock_key, project_id, use_redis_lock
                )

                if not db_lock_acquired:
                    return await self._handle_lock_not_acquired(project_id)

                # Lock acquired, proceed with double-check
                existing = await self._repository.find_by_project(project_id)

                if existing:
                    result = await self._handle_existing_sandbox(existing, project_id)
                    if result is not None:
                        return result

                # Create new sandbox (under both locks)
                # The distributed lock is held until this method returns
                return await self._create_new_sandbox(
                    project_id=project_id,
                    tenant_id=tenant_id,
                    profile=profile,
                    config_override=config_override,
                )
            finally:
                await self._release_distributed_lock(lock_handle, project_id, use_redis_lock)

    async def _acquire_distributed_lock(
        self,
        lock_key: str,
        project_id: str,
        use_redis_lock: bool,
    ) -> tuple[Any, bool]:
        """Acquire distributed lock via Redis or PostgreSQL fallback.

        Returns:
            Tuple of (lock_handle, lock_acquired).
        """
        lock_handle = None
        if use_redis_lock:
            # Use Redis distributed lock (preferred)
            lock_handle = await self._distributed_lock.acquire(
                key=lock_key,
                ttl=120,  # 2 minutes for container creation
                blocking=True,
                timeout=30.0,
            )
            db_lock_acquired = lock_handle is not None
            if db_lock_acquired:
                logger.debug(f"Redis lock acquired for project {project_id}: {lock_handle}")
        else:
            # Fallback to PostgreSQL advisory lock
            db_lock_acquired = await self._repository.acquire_project_lock(
                project_id, blocking=True, timeout_seconds=30
            )
        return lock_handle, db_lock_acquired

    async def _release_distributed_lock(
        self,
        lock_handle: Any,
        project_id: str,
        use_redis_lock: bool,
    ) -> None:
        """Release distributed lock after container creation completes."""
        if use_redis_lock and lock_handle:
            released = await self._distributed_lock.release(lock_handle)
            if released:
                logger.debug(f"Redis lock released for project {project_id}")
            else:
                logger.warning(f"Failed to release Redis lock for project {project_id}")
        elif not use_redis_lock:
            # Fallback: release PostgreSQL advisory lock
            await self._repository.release_project_lock(project_id)

    async def _handle_lock_not_acquired(self, project_id: str) -> SandboxInfo:
        """Handle case when distributed lock could not be acquired.

        Waits briefly and checks for an existing usable sandbox.

        Raises:
            SandboxLockTimeoutError: If no usable sandbox is found.
        """
        logger.info(f"Project {project_id} sandbox creation locked by another worker, waiting...")
        await asyncio.sleep(1.0)
        existing = await self._repository.find_by_project(project_id)
        if existing and existing.is_usable():
            existing.mark_accessed()
            await self._repository.save(existing)
            return await self._get_sandbox_info(existing)
        raise SandboxLockTimeoutError(
            message=f"Could not acquire lock for project {project_id}",
            project_id=project_id,
            timeout_seconds=30.0,
        )

    async def _handle_existing_sandbox(
        self,
        existing: ProjectSandbox,
        project_id: str,
    ) -> SandboxInfo | None:
        """Handle an existing sandbox association based on its status.

        Returns:
            SandboxInfo if the sandbox is usable/recovered, None if a new sandbox
            should be created (after cleanup).
        """
        logger.debug(
            f"Found existing sandbox for project {project_id}: "
            f"status={existing.status}, status_value={existing.status.value}"
        )

        # Dispatch to status-specific handlers
        _status_handlers: dict[ProjectSandboxStatus, Any] = {
            ProjectSandboxStatus.RUNNING: self._handle_status_running,
            ProjectSandboxStatus.STOPPED: self._handle_status_stopped,
            ProjectSandboxStatus.ERROR: self._handle_status_error,
            ProjectSandboxStatus.UNHEALTHY: self._handle_status_unhealthy,
            ProjectSandboxStatus.CREATING: self._handle_status_creating,
            ProjectSandboxStatus.TERMINATED: self._handle_status_terminated,
        }

        # RUNNING status is also triggered for any other "usable" state
        if existing.is_usable():
            return await self._handle_status_running(existing, project_id)

        handler = _status_handlers.get(existing.status)
        if handler is not None:
            return cast("SandboxInfo | None", await handler(existing, project_id))

        # Unknown status, fall through to create new
        return None

    async def _handle_status_running(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox in RUNNING/usable state.

        Verifies the container actually exists before returning.
        """
        container_exists = await self._adapter.container_exists(existing.sandbox_id)
        if container_exists:
            existing.mark_accessed()
            await self._repository.save(existing)
            return await self._get_sandbox_info(existing)

        # Container was killed/deleted externally, need to rebuild
        logger.warning(
            f"Project {project_id} sandbox {existing.sandbox_id} "
            f"marked as {existing.status.value} but container doesn't exist. "
            f"Triggering rebuild..."
        )
        await self._cleanup_failed_sandbox(existing)
        return None

    async def _handle_status_stopped(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox in STOPPED state by restarting."""
        logger.info(f"Project {project_id} sandbox stopped, restarting...")
        return await self._restart_sandbox(existing)

    async def _handle_status_error(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox in ERROR state by cleaning up for recreation."""
        logger.warning(f"Project {project_id} sandbox in error state, recreating...")
        await self._cleanup_failed_sandbox(existing)
        return None

    async def _handle_status_unhealthy(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox in UNHEALTHY state with recovery attempt."""
        if not self._auto_recover:
            return None
        logger.info(f"Project {project_id} sandbox unhealthy, attempting recovery...")
        recovered = await self._recover_sandbox(existing)
        if recovered:
            return await self._get_sandbox_info(existing)
        # Recovery failed, recreate
        await self._cleanup_failed_sandbox(existing)
        return None

    async def _handle_status_creating(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox stuck in CREATING state."""
        container_exists = await self._adapter.container_exists(existing.sandbox_id)
        if container_exists:
            # Container exists, wait for it
            logger.info(f"Project {project_id} sandbox is being created, waiting...")
            return await self._get_sandbox_info(existing)

        # CREATING but no container - previous creation failed
        logger.warning(
            f"Project {project_id} sandbox stuck in CREATING state "
            f"but container doesn't exist. Rebuilding..."
        )
        await self._cleanup_failed_sandbox(existing)
        return None

    async def _handle_status_terminated(
        self, existing: ProjectSandbox, project_id: str
    ) -> SandboxInfo | None:
        """Handle sandbox in TERMINATED state by cleaning up for recreation."""
        logger.info(f"Project {project_id} sandbox terminated, creating new...")
        await self._cleanup_failed_sandbox(existing)
        return None

    async def get_project_sandbox(self, project_id: str) -> SandboxInfo | None:
        """Get sandbox info for a project if it exists.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo if sandbox exists, None otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return None

        return await self._get_sandbox_info(association)

    async def ensure_sandbox_running(
        self,
        project_id: str,
        tenant_id: str,
    ) -> SandboxInfo:
        """Ensure project's sandbox is running, creating if necessary.

        This is a convenience method that guarantees a running sandbox.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            SandboxInfo for the running sandbox
        """
        info = await self.get_or_create_sandbox(project_id, tenant_id)

        if not info.is_healthy:
            raise SandboxNotFoundError(
                message=f"Could not ensure sandbox is running for project {project_id}",
                project_id=project_id,
            )

        return info

    async def execute_tool(
        self,
        project_id: str,
        tool_name: str,
        arguments: dict[str, Any],
        timeout: float = 30.0,
    ) -> dict[str, Any]:
        """Execute a tool in the project's sandbox.

        Automatically ensures the sandbox is running before execution.

        Args:
            project_id: The project ID
            tool_name: MCP tool name (bash, read, write, etc.)
            arguments: Tool arguments
            timeout: Execution timeout

        Returns:
            Tool execution result
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

    async def terminate_project_sandbox(
        self,
        project_id: str,
        delete_association: bool = True,
    ) -> bool:
        """Terminate the sandbox for a project.

        Args:
            project_id: The project ID
            delete_association: Whether to delete the association record

        Returns:
            True if terminated successfully
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

    async def restart_project_sandbox(self, project_id: str) -> SandboxInfo:
        """Restart the sandbox for a project.

        Uses per-project lock to prevent concurrent restart operations
        on the same project.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo for the restarted sandbox
        """
        # Acquire per-project lock to prevent concurrent restart
        project_lock = await self._get_project_lock(project_id)
        async with project_lock:
            association = await self._repository.find_by_project(project_id)
            if not association:
                raise SandboxNotFoundError(
                    message=f"No sandbox found for project {project_id}",
                    project_id=project_id,
                )

            return await self._restart_sandbox(association)

    async def list_project_sandboxes(
        self,
        tenant_id: str,
        status: ProjectSandboxStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SandboxInfo]:
        """List all project sandboxes for a tenant.

        Args:
            tenant_id: The tenant ID
            status: Optional status filter
            limit: Maximum results
            offset: Pagination offset

        Returns:
            List of SandboxInfo
        """
        associations = await self._repository.find_by_tenant(
            tenant_id=tenant_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        results: list[SandboxInfo] = []
        if not associations:
            return results

        # Parallelize info retrieval
        tasks = [self._get_sandbox_info(a) for a in associations]
        gathered = await asyncio.gather(*tasks, return_exceptions=True)
        for association, result in zip(associations, gathered, strict=False):
            if isinstance(result, Exception):
                logger.warning(f"Failed to get info for sandbox {association.sandbox_id}: {result}")
            else:
                results.append(result)

        return results

    async def cleanup_stale_sandboxes(
        self,
        max_idle_seconds: int = 3600,
        dry_run: bool = False,
    ) -> list[str]:
        """Clean up sandboxes that haven't been accessed recently.

        Args:
            max_idle_seconds: Maximum idle time before cleanup
            dry_run: If True, only return IDs without terminating

        Returns:
            List of terminated sandbox IDs
        """
        stale = await self._repository.find_stale(
            max_idle_seconds=max_idle_seconds,
            limit=100,
        )

        terminated = []
        for association in stale:
            if not dry_run:
                try:
                    await self._adapter.terminate_sandbox(association.sandbox_id)
                    association.mark_terminated()
                    await self._repository.save(association)
                except Exception as e:
                    logger.error(f"Failed to terminate stale sandbox {association.sandbox_id}: {e}")
                    continue

            terminated.append(association.sandbox_id)

        return terminated

    async def sync_sandbox_status(self, project_id: str) -> SandboxInfo:
        """Synchronize the database status with actual container status.

        Args:
            project_id: The project ID

        Returns:
            Updated SandboxInfo
        """
        # Acquire project lock to prevent concurrent status updates
        project_lock = await self._get_project_lock(project_id)
        async with project_lock:
            association = await self._repository.find_by_project(project_id)
            if not association:
                raise SandboxNotFoundError(
                    message=f"No sandbox found for project {project_id}",
                    project_id=project_id,
                )

            # Get actual container status
            instance = await self._adapter.get_sandbox(association.sandbox_id)

            if not instance:
                # Container doesn't exist but association does
                if association.status not in (
                    ProjectSandboxStatus.TERMINATED,
                    ProjectSandboxStatus.ERROR,
                ):
                    association.mark_error("Container not found")
                    await self._repository.save(association)
            else:
                # Update status based on container state
                container_status = instance.status

                if container_status == SandboxStatus.RUNNING:
                    association.mark_healthy()
                elif container_status == SandboxStatus.STOPPED:
                    association.mark_stopped()
                elif container_status == SandboxStatus.ERROR:
                    association.mark_error("Container in error state")

                await self._repository.save(association)

            return await self._get_sandbox_info(association)

    # -------------------------------------------------------------------------
    # Private helper methods
    # -------------------------------------------------------------------------

    async def _create_new_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        profile: SandboxProfileType | None = None,
        config_override: dict[str, Any] | None = None,
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
            # Resolve configuration
            config = self._resolve_config(profile, config_override)

            # Create sandbox container with project/tenant identification
            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
                project_id=project_id,
                tenant_id=tenant_id,
            )

            # Update association with success
            association.sandbox_id = instance.id  # Use actual container ID
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.now(UTC)
            association.mark_healthy()
            await self._repository.save(association)

            # Connect MCP
            try:
                await self._adapter.connect_mcp(instance.id)
            except Exception as e:
                logger.warning(f"Failed to connect MCP for {instance.id}: {e}")

            logger.info(f"Created new sandbox {instance.id} for project {project_id}")
            return await self._get_sandbox_info(association)

        except Exception as e:
            logger.error(f"Failed to create sandbox for project {project_id}: {e}")
            association.mark_error(str(e))
            await self._repository.save(association)
            raise

    async def _restart_sandbox(self, association: ProjectSandbox) -> SandboxInfo:
        """Restart a stopped sandbox."""
        try:
            # For Docker-based sandboxes, we need to recreate since
            # containers can't be restarted after being stopped
            return await self._recreate_sandbox(association)
        except Exception as e:
            logger.error(f"Failed to restart sandbox {association.sandbox_id}: {e}")
            association.mark_error(f"Restart failed: {e}")
            await self._repository.save(association)
            raise

    async def _recreate_sandbox(self, association: ProjectSandbox) -> SandboxInfo:
        """Recreate a sandbox while preserving the association and sandbox_id.

        CRITICAL: This method preserves the original sandbox_id so that
        cached tool references in ReActAgent remain valid. The old container
        is terminated and a new one is created with the same ID.
        """
        project_path = f"/tmp/memstack_{association.project_id}"

        # IMPORTANT: Preserve the original sandbox_id to maintain tool references
        # ReActAgent's SandboxMCPToolWrapper caches the sandbox_id, so changing it
        # would break tool execution until the agent is reinitialized
        original_sandbox_id = association.sandbox_id

        # CRITICAL: Clean up ALL existing containers for this project first
        # This prevents orphan containers from accumulating
        logger.info(
            f"Recreating sandbox for project {association.project_id}, "
            f"cleaning up old container {original_sandbox_id}..."
        )

        # Step 1: Terminate the old sandbox explicitly
        try:
            await self._adapter.terminate_sandbox(original_sandbox_id)
            logger.info(f"Terminated old sandbox {original_sandbox_id}")
        except Exception as e:
            logger.warning(f"Could not terminate old sandbox {original_sandbox_id}: {e}")

        # Clear MCPApp resources so the frontend doesn't show stale READY state (D3)
        _clear_task = asyncio.create_task(self._clear_mcp_app_resources(association.project_id))
        self._background_tasks.add(_clear_task)
        _clear_task.add_done_callback(self._background_tasks.discard)

        # Step 2: Clean up any other containers for this project (orphans)
        try:
            cleaned = await self._adapter.cleanup_project_containers(association.project_id)
            if cleaned > 0:
                logger.info(
                    f"Cleaned up {cleaned} additional container(s) for project {association.project_id}"
                )
        except Exception as e:
            logger.warning(f"Failed to cleanup project containers: {e}")

        # Keep the same sandbox_id for tool compatibility
        association.status = ProjectSandboxStatus.CREATING
        association.error_message = None
        await self._repository.save(association)

        try:
            # Create new sandbox with the SAME sandbox_id for tool compatibility
            config = self._resolve_config(self._default_profile, None)
            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
                project_id=association.project_id,
                tenant_id=association.tenant_id,
                sandbox_id=original_sandbox_id,  # Reuse original sandbox_id
            )

            # Update status (sandbox_id should remain the same)
            association.sandbox_id = instance.id
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.now(UTC)
            association.mark_healthy()
            await self._repository.save(association)

            # Connect MCP
            try:
                await self._adapter.connect_mcp(instance.id)
            except Exception as e:
                logger.warning(f"Failed to connect MCP for {instance.id}: {e}")

            # Reinstall child MCP servers that were configured for this project (D1)
            _reinstall_task = asyncio.create_task(
                self._reinstall_mcp_servers(
                    project_id=association.project_id,
                    tenant_id=association.tenant_id,
                )
            )
            self._background_tasks.add(_reinstall_task)
            _reinstall_task.add_done_callback(self._background_tasks.discard)

            logger.info(
                f"Recreated sandbox for project {association.project_id}: "
                f"sandbox_id={instance.id} (preserved)"
            )
            return await self._get_sandbox_info(association)

        except Exception as e:
            logger.error(f"Failed to recreate sandbox: {e}")
            association.mark_error(f"Recreation failed: {e}")
            await self._repository.save(association)
            raise

    async def _reinstall_mcp_servers(self, project_id: str, tenant_id: str) -> None:
        """Reinstall all enabled child MCP servers after sandbox recreation (D1 fix).

        Runs as a background task after the new sandbox container is ready.
        Each server failure is logged as a warning but does not abort the others.

        Args:
            project_id: The project whose servers to reinstall.
            tenant_id: Tenant ID for sandbox access scoping.
        """
        try:
            from src.application.services.mcp_app_service import MCPAppService
            from src.application.services.mcp_runtime_service import MCPRuntimeService
            from src.application.services.sandbox_mcp_server_manager import (
                SandboxMCPServerManager,
            )
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
                SqlMCPAppRepository,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
                SqlMCPServerRepository,
            )
            from src.infrastructure.mcp.resource_resolver import MCPAppResourceResolver

            async with async_session_factory() as session:
                server_repo = SqlMCPServerRepository(session)
                app_repo = SqlMCPAppRepository(session)
                manager: SandboxMCPServerManager
                resource_resolver = MCPAppResourceResolver(manager_factory=lambda: manager)
                app_service = MCPAppService(
                    app_repo=app_repo,
                    resource_resolver=resource_resolver,
                )
                manager = SandboxMCPServerManager(
                    sandbox_resource=self,
                    app_service=app_service,
                )
                runtime = MCPRuntimeService(
                    db=session,
                    server_repo=server_repo,
                    app_repo=app_repo,
                    app_service=app_service,
                    sandbox_manager=manager,
                )
                result = await runtime.reconcile_project(project_id=project_id, tenant_id=tenant_id)
                await session.commit()
                logger.info(
                    "Reconciled MCP runtime after sandbox recreation: "
                    "project=%s enabled=%d restored=%d failed=%d already_running=%d",
                    project_id,
                    result.total_enabled_servers,
                    result.restored,
                    result.failed,
                    result.already_running,
                )

        except Exception as e:
            logger.warning("_reinstall_mcp_servers failed for project %s: %s", project_id, e)

    async def _install_single_mcp_server(
        self,
        project_id: str,
        server_name: str,
        server_type: str,
        transport_config: dict[str, Any],
    ) -> None:
        """Install and start a single MCP server in the project sandbox.

        Args:
            project_id: The project ID.
            server_name: MCP server name.
            server_type: Transport type (stdio, http, sse, websocket).
            transport_config: Transport configuration dict.
        """
        import json

        from src.application.services.sandbox_mcp_server_manager import (
            MCP_INSTALL_TIMEOUT,
            MCP_START_TIMEOUT,
            TOOL_INSTALL,
            TOOL_START,
        )

        config_json = json.dumps(transport_config)

        install_result = await self.execute_tool(
            project_id=project_id,
            tool_name=TOOL_INSTALL,
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=MCP_INSTALL_TIMEOUT,
        )

        # Check install success
        content = install_result.get("content", [])
        if isinstance(content, list) and content:
            first = content[0] if isinstance(content[0], dict) else {}
            text = first.get("text", "{}")
        else:
            text = str(install_result)
        try:
            import json as _json

            data = _json.loads(text) if isinstance(text, str) else {}
        except Exception:
            data = {}
        if not data.get("success", False) and not install_result.get("success", False):
            raise RuntimeError(f"Install failed for '{server_name}': {data.get('error', text)}")

        await self.execute_tool(
            project_id=project_id,
            tool_name=TOOL_START,
            arguments={
                "name": server_name,
                "server_type": server_type,
                "transport_config": config_json,
            },
            timeout=MCP_START_TIMEOUT,
        )

    async def _clear_mcp_app_resources(self, project_id: str) -> None:
        """Clear MCPApp resources for a project after sandbox recreation (D3 fix).

        Marks all non-disabled MCPApps as DISCOVERED so the frontend does not
        show stale READY apps that point to a resource in the old sandbox.

        Args:
            project_id: The project whose app resources to clear.
        """
        try:
            from src.application.services.mcp_app_service import MCPAppService
            from src.infrastructure.adapters.secondary.persistence.database import (
                async_session_factory,
            )
            from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
                SqlMCPAppRepository,
            )
            from src.infrastructure.mcp.resource_resolver import MCPAppResourceResolver

            async with async_session_factory() as session:
                app_repo = SqlMCPAppRepository(session)
                # resource_resolver is not used by clear_resources_for_project
                service = MCPAppService(
                    app_repo=app_repo,
                    resource_resolver=MCPAppResourceResolver(manager_factory=lambda: None),
                )
                count = await service.clear_resources_for_project(project_id)
                await session.commit()
                if count > 0:
                    logger.info(
                        "Cleared %d MCPApp resource(s) for project %s after sandbox recreation",
                        count,
                        project_id,
                    )
        except Exception as e:
            logger.warning("_clear_mcp_app_resources failed for project %s: %s", project_id, e)

    async def _recover_sandbox(self, association: ProjectSandbox) -> bool:
        """Attempt to recover an unhealthy sandbox."""
        try:
            # Try health check first
            healthy = await self._adapter.health_check(association.sandbox_id)
            if healthy:
                association.mark_healthy()
                await self._repository.save(association)
                return True

            # Health check failed, try to recreate
            await self._recreate_sandbox(association)
            return True

        except Exception as e:
            logger.error(f"Recovery failed for sandbox {association.sandbox_id}: {e}")
            return False

    async def _cleanup_failed_sandbox(self, association: ProjectSandbox) -> None:
        """Clean up a failed sandbox before recreating.

        This method:
        1. Terminates the Docker container (if exists)
        2. Cleans up any orphan containers for this project
        3. Deletes the database association record
        """
        # Terminate the container by sandbox_id - container might not exist
        with contextlib.suppress(Exception):
            await self._adapter.terminate_sandbox(association.sandbox_id)

        try:
            # Also cleanup any orphan containers for this project
            await self._adapter.cleanup_project_containers(association.project_id)
        except Exception as e:
            logger.warning(
                f"Failed to cleanup orphan containers for project {association.project_id}: {e}"
            )

        # Delete the database association record to allow fresh creation
        try:
            await self._repository.delete(association.id)
            logger.info(
                f"Deleted sandbox association {association.id} for project {association.project_id}"
            )
        except Exception as e:
            logger.error(f"Failed to delete sandbox association {association.id}: {e}")

    async def _get_sandbox_info(self, association: ProjectSandbox) -> SandboxInfo:
        """Build SandboxInfo from association and container."""
        instance = await self._adapter.get_sandbox(association.sandbox_id)

        is_healthy = (
            association.status == ProjectSandboxStatus.RUNNING
            and instance is not None
            and instance.status == SandboxStatus.RUNNING
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
        )

    def _resolve_config(
        self,
        profile: SandboxProfileType | None,
        config_override: dict[str, Any] | None,
    ) -> SandboxConfig:
        """Resolve sandbox configuration from profile and overrides."""
        profile_type = profile or self._default_profile
        sandbox_profile = get_sandbox_profile(profile_type)

        # Get image from profile or use default
        image = sandbox_profile.image_name or "sandbox-mcp-server:latest"

        # Apply global overrides if set
        memory_limit = self._memory_limit_override or sandbox_profile.memory_limit
        cpu_limit = self._cpu_limit_override or sandbox_profile.cpu_limit

        config = SandboxConfig(
            image=image,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
            timeout_seconds=sandbox_profile.timeout_seconds,
            desktop_enabled=sandbox_profile.desktop_enabled,
            environment=config_override.get("environment") if config_override else {},
        )

        # Apply overrides
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

    async def sync_and_repair_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        auto_rebuild: bool = True,
    ) -> SandboxInfo:
        """Synchronize sandbox state with actual Docker state and optionally repair.

        This method is useful for:
        1. Detecting containers that were externally killed/deleted
        2. Repairing database state that is out of sync with Docker
        3. Ensuring a working sandbox exists for the project

        Args:
            project_id: The project ID
            tenant_id: The tenant ID (needed if rebuild is required)
            auto_rebuild: If True, automatically rebuild if container is missing

        Returns:
            SandboxInfo with current state (possibly after rebuild)

        Raises:
            SandboxNotFoundError: If no sandbox exists and auto_rebuild is False
        """
        association = await self._repository.find_by_project(project_id)

        if not association:
            if auto_rebuild:
                logger.info(f"No sandbox found for project {project_id}, creating...")
                return await self.get_or_create_sandbox(project_id, tenant_id)
            raise SandboxNotFoundError(
                message=f"No sandbox found for project {project_id}",
                project_id=project_id,
            )

        # Check if container actually exists
        container_exists = await self._adapter.container_exists(association.sandbox_id)

        if container_exists:
            # Container exists, ensure state is correct
            if association.status not in [
                ProjectSandboxStatus.RUNNING,
                ProjectSandboxStatus.UNHEALTHY,
            ]:
                logger.info(
                    f"Project {project_id} container exists but state is {association.status.value}, "
                    f"updating to RUNNING"
                )
                association.status = ProjectSandboxStatus.RUNNING
                association.mark_healthy()
                await self._repository.save(association)

            return await self._get_sandbox_info(association)

        # Container doesn't exist
        logger.warning(
            f"Project {project_id} sandbox {association.sandbox_id} "
            f"is marked as {association.status.value} but container doesn't exist"
        )

        if not auto_rebuild:
            # Update state to reflect reality
            association.status = ProjectSandboxStatus.ERROR
            association.mark_error("Container was externally deleted")
            await self._repository.save(association)
            return await self._get_sandbox_info(association)

        # Auto-rebuild: use get_or_create_sandbox which handles locking properly
        logger.info(f"Auto-rebuilding sandbox for project {project_id}...")
        return await self.get_or_create_sandbox(project_id, tenant_id)

    async def verify_container_exists(self, project_id: str) -> bool:
        """Quick check if the container for a project actually exists.

        Useful for UI to show accurate status without triggering rebuild.

        Args:
            project_id: The project ID to check

        Returns:
            True if container exists and is running, False otherwise
        """
        association = await self._repository.find_by_project(project_id)
        if not association:
            return False

        return await self._adapter.container_exists(association.sandbox_id)
