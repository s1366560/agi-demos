"""Project Sandbox Lifecycle Service.

Manages the lifecycle of project-dedicated sandboxes:
- Each project has exactly one persistent sandbox
- Lazy creation on first use
- Health monitoring and auto-recovery
- Resource cleanup on project deletion
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.application.services.sandbox_profile import (
    SandboxProfile,
    SandboxProfileType,
    get_profile as get_sandbox_profile,
)
from src.domain.model.sandbox.project_sandbox import (
    ProjectSandbox,
    ProjectSandboxStatus,
)
from src.domain.ports.repositories.project_sandbox_repository import (
    ProjectSandboxRepository,
)
from src.domain.ports.services.sandbox_port import (
    SandboxConfig,
    SandboxNotFoundError,
    SandboxStatus,
)
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import (
    MCPSandboxAdapter,
)

logger = logging.getLogger(__name__)


@dataclass
class SandboxInfo:
    """Information about a project's sandbox."""

    sandbox_id: str
    project_id: str
    tenant_id: str
    status: str
    endpoint: Optional[str] = None
    websocket_url: Optional[str] = None
    mcp_port: Optional[int] = None
    desktop_port: Optional[int] = None
    terminal_port: Optional[int] = None
    desktop_url: Optional[str] = None
    terminal_url: Optional[str] = None
    created_at: Optional[datetime] = None
    last_accessed_at: Optional[datetime] = None
    is_healthy: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
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
        default_profile: SandboxProfileType = SandboxProfileType.STANDARD,
        health_check_interval_seconds: int = 60,
        auto_recover: bool = True,
    ):
        """Initialize the lifecycle service.

        Args:
            repository: Repository for ProjectSandbox associations
            sandbox_adapter: Adapter for sandbox container operations
            default_profile: Default sandbox profile
            health_check_interval_seconds: Minimum seconds between health checks
            auto_recover: Whether to auto-recover unhealthy sandboxes
        """
        self._repository = repository
        self._adapter = sandbox_adapter
        self._default_profile = default_profile
        self._health_check_interval = health_check_interval_seconds
        self._auto_recover = auto_recover

    async def get_or_create_sandbox(
        self,
        project_id: str,
        tenant_id: str,
        profile: Optional[SandboxProfileType] = None,
        config_override: Optional[Dict[str, Any]] = None,
    ) -> SandboxInfo:
        """Get existing sandbox or create a new one for the project.

        This is the primary method for accessing project sandboxes. It ensures
        that each project has exactly one persistent sandbox.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID for scoping
            profile: Sandbox profile (lite, standard, full)
            config_override: Optional configuration overrides

        Returns:
            SandboxInfo with connection details and status

        Raises:
            SandboxError: If sandbox creation fails
        """
        # Check if project already has a sandbox
        existing = await self._repository.find_by_project(project_id)

        if existing:
            # Check if existing sandbox is usable
            if existing.is_usable():
                existing.mark_accessed()
                await self._repository.save(existing)
                return await self._get_sandbox_info(existing)

            # Sandbox exists but not running - try to recover or recreate
            if existing.status == ProjectSandboxStatus.STOPPED:
                logger.info(f"Project {project_id} sandbox stopped, restarting...")
                return await self._restart_sandbox(existing)

            if existing.status == ProjectSandboxStatus.ERROR:
                logger.warning(f"Project {project_id} sandbox in error state, recreating...")
                await self._cleanup_failed_sandbox(existing)
                # Fall through to create new

            if existing.status == ProjectSandboxStatus.UNHEALTHY and self._auto_recover:
                logger.info(f"Project {project_id} sandbox unhealthy, attempting recovery...")
                recovered = await self._recover_sandbox(existing)
                if recovered:
                    return await self._get_sandbox_info(existing)
                # Recovery failed, recreate
                await self._cleanup_failed_sandbox(existing)

        # Create new sandbox
        return await self._create_new_sandbox(
            project_id=project_id,
            tenant_id=tenant_id,
            profile=profile,
            config_override=config_override,
        )

    async def get_project_sandbox(self, project_id: str) -> Optional[SandboxInfo]:
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
        arguments: Dict[str, Any],
        timeout: float = 30.0,
    ) -> Dict[str, Any]:
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

            logger.info(f"Terminated sandbox for project {project_id}")
            return True

        except Exception as e:
            logger.error(f"Failed to terminate sandbox for project {project_id}: {e}")
            return False

    async def restart_project_sandbox(self, project_id: str) -> SandboxInfo:
        """Restart the sandbox for a project.

        Args:
            project_id: The project ID

        Returns:
            SandboxInfo for the restarted sandbox
        """
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
        status: Optional[ProjectSandboxStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[SandboxInfo]:
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

        results = []
        for association in associations:
            try:
                info = await self._get_sandbox_info(association)
                results.append(info)
            except Exception as e:
                logger.warning(f"Failed to get info for sandbox {association.sandbox_id}: {e}")

        return results

    async def cleanup_stale_sandboxes(
        self,
        max_idle_seconds: int = 3600,
        dry_run: bool = False,
    ) -> List[str]:
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
            # Resolve configuration
            config = self._resolve_config(profile, config_override)

            # Create sandbox container
            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
            )

            # Update association with success
            association.sandbox_id = instance.id  # Use actual container ID
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.utcnow()
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
        """Recreate a sandbox while preserving the association."""
        project_path = f"/tmp/memstack_{association.project_id}"

        # Generate new sandbox ID
        old_sandbox_id = association.sandbox_id
        new_sandbox_id = f"proj-sb-{uuid.uuid4().hex[:12]}"

        association.sandbox_id = new_sandbox_id
        association.status = ProjectSandboxStatus.CREATING
        association.error_message = None
        await self._repository.save(association)

        try:
            # Create new sandbox
            config = self._resolve_config(self._default_profile, None)
            instance = await self._adapter.create_sandbox(
                project_path=project_path,
                config=config,
            )

            # Update with actual container ID
            association.sandbox_id = instance.id
            association.status = ProjectSandboxStatus.RUNNING
            association.started_at = datetime.utcnow()
            association.mark_healthy()
            await self._repository.save(association)

            # Connect MCP
            try:
                await self._adapter.connect_mcp(instance.id)
            except Exception as e:
                logger.warning(f"Failed to connect MCP for {instance.id}: {e}")

            logger.info(
                f"Recreated sandbox for project {association.project_id}: "
                f"{old_sandbox_id} -> {instance.id}"
            )
            return await self._get_sandbox_info(association)

        except Exception as e:
            logger.error(f"Failed to recreate sandbox: {e}")
            association.mark_error(f"Recreation failed: {e}")
            await self._repository.save(association)
            raise

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
        """Clean up a failed sandbox before recreating."""
        try:
            await self._adapter.terminate_sandbox(association.sandbox_id)
        except Exception:
            # Ignore errors during cleanup
            pass

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
        profile: Optional[SandboxProfileType],
        config_override: Optional[Dict[str, Any]],
    ) -> SandboxConfig:
        """Resolve sandbox configuration from profile and overrides."""
        profile_type = profile or self._default_profile
        sandbox_profile = get_sandbox_profile(profile_type)

        config = SandboxConfig(
            memory_limit=sandbox_profile.memory_limit,
            cpu_limit=sandbox_profile.cpu_limit,
            timeout_seconds=sandbox_profile.timeout_seconds,
            desktop_enabled=sandbox_profile.desktop_enabled,
            environment=config_override.get("environment") if config_override else {},
        )

        # Apply overrides
        if config_override:
            if "memory_limit" in config_override:
                config.memory_limit = config_override["memory_limit"]
            if "cpu_limit" in config_override:
                config.cpu_limit = config_override["cpu_limit"]
            if "timeout_seconds" in config_override:
                config.timeout_seconds = config_override["timeout_seconds"]
            if "desktop_enabled" in config_override:
                config.desktop_enabled = config_override["desktop_enabled"]

        return config
