"""DI sub-container for sandbox domain."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.configuration.config import Settings
from src.domain.model.sandbox.profiles import SandboxProfileType
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.sandbox_runtime import SandboxApplicationServicesV2


class SandboxContainer:
    """Sub-container for sandbox-related services.

    Provides factory methods for sandbox repository, orchestrator,
    tool registry, resource, and lifecycle service.
    Cross-domain dependencies are injected via callbacks.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        redis_client: Any = None,
        settings: Settings | None = None,
        distributed_lock_factory: Callable[..., Any] | None = None,
    ) -> None:
        self._db = db
        self._redis_client = redis_client
        self._settings = settings
        self._distributed_lock_factory = distributed_lock_factory

    def project_sandbox_repository(self) -> SqlProjectSandboxRepository:
        """Get SqlProjectSandboxRepository for sandbox persistence."""
        assert self._db is not None
        return SqlProjectSandboxRepository(self._db)

    def sandbox_orchestrator(self) -> SandboxOrchestrator:
        """Project the generation-owned sandbox orchestrator."""
        return self._sandbox_application_services().orchestrator

    def sandbox_tool_registry(self) -> Any:
        """Get SandboxToolRegistry for dynamic MCP tool registration to Agent."""
        from src.application.services.sandbox_tool_registry import SandboxToolRegistry

        return SandboxToolRegistry(
            redis_client=self._redis_client,
            mcp_adapter=self._sandbox_application_services().adapter,
        )

    def sandbox_resource(self) -> SandboxResourcePort:
        """Get SandboxResourcePort for agent workflow sandbox access."""
        from src.application.services.unified_sandbox_service import UnifiedSandboxService

        distributed_lock = (
            self._distributed_lock_factory() if self._distributed_lock_factory else None
        )
        return UnifiedSandboxService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=self._sandbox_application_services().adapter,
            distributed_lock=distributed_lock,
            default_profile=SandboxProfileType(self._settings.sandbox_profile_type)
            if self._settings
            else SandboxProfileType.STANDARD,
            health_check_interval_seconds=60,
            auto_recover=True,
            memory_limit_override=self._settings.sandbox_memory_limit if self._settings else None,
            cpu_limit_override=self._settings.sandbox_cpu_limit if self._settings else None,
            host_source_volume=(
                {
                    self._settings.sandbox_host_source_path: (
                        self._settings.sandbox_host_source_mount_point
                    )
                }
                if self._settings and self._settings.sandbox_host_source_path
                else None
            ),
            host_memstack_volume=self._resolve_memstack_volume(),
            host_docker_socket_volume=self._resolve_docker_socket_volume(),
        )

    def workspace_sync_service(self) -> Any:
        """Get WorkspaceSyncService for workspace state persistence across sandbox lifecycles."""
        from src.application.services.workspace_sync_service import WorkspaceSyncService

        return WorkspaceSyncService(
            workspace_base=self._settings.sandbox_workspace_base if self._settings else "/tmp",
        )

    def project_sandbox_lifecycle_service(self) -> Any:
        """Get ProjectSandboxLifecycleService for project-dedicated sandbox management."""
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )

        distributed_lock = (
            self._distributed_lock_factory() if self._distributed_lock_factory else None
        )
        return ProjectSandboxLifecycleService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=self._sandbox_application_services().adapter,
            distributed_lock=distributed_lock,
            default_profile=SandboxProfileType(self._settings.sandbox_profile_type)
            if self._settings
            else SandboxProfileType.STANDARD,
            health_check_interval_seconds=60,
            auto_recover=True,
            memory_limit_override=self._settings.sandbox_memory_limit if self._settings else None,
            cpu_limit_override=self._settings.sandbox_cpu_limit if self._settings else None,
            host_source_volume=(
                {
                    self._settings.sandbox_host_source_path: (
                        self._settings.sandbox_host_source_mount_point
                    )
                }
                if self._settings and self._settings.sandbox_host_source_path
                else None
            ),
            host_memstack_volume=self._resolve_memstack_volume(),
            host_docker_socket_volume=self._resolve_docker_socket_volume(),
            workspace_sync=self.workspace_sync_service(),
        )

    def sandbox_mcp_server_manager(self) -> Any:
        """Get SandboxMCPServerManager for managing user MCP servers in sandbox."""
        from src.application.services.sandbox_mcp_server_manager import (
            SandboxMCPServerManager,
        )

        return SandboxMCPServerManager(
            sandbox_resource=self.sandbox_resource(),
            app_service=self.mcp_app_service() if self._db else None,
        )

    def mcp_app_service(self) -> Any:
        """Get MCPAppService for MCP App lifecycle management."""
        from src.application.services.mcp_app_service import MCPAppService
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
            SqlMCPAppRepository,
        )
        from src.infrastructure.mcp.resource_resolver import MCPAppResourceResolver

        assert self._db is not None
        app_repo = SqlMCPAppRepository(self._db)
        # Use factory callable to break circular dependency:
        # MCPAppService -> ResourceResolver -> SandboxMCPServerManager -> MCPAppService
        resource_resolver = MCPAppResourceResolver(
            manager_factory=lambda: self.sandbox_mcp_server_manager(),
        )
        return MCPAppService(app_repo=app_repo, resource_resolver=resource_resolver)

    def mcp_runtime_service(self) -> Any:
        """Get MCPRuntimeService for unified MCP server+app lifecycle.

        Centralises construction so routers no longer need direct SQL
        repository imports (fix H2).  Injects lifecycle-event and project
        repos so the service has no direct SQLAlchemy dependency (fix C5).
        """
        from src.application.services.mcp_runtime_service import MCPRuntimeService
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_app_repository import (
            SqlMCPAppRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_lifecycle_event_repository import (
            SqlMCPLifecycleEventRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_mcp_server_repository import (
            SqlMCPServerRepository,
        )
        from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
            SqlProjectRepository,
        )

        assert self._db is not None
        return MCPRuntimeService(
            server_repo=SqlMCPServerRepository(self._db),
            app_repo=SqlMCPAppRepository(self._db),
            app_service=self.mcp_app_service(),
            sandbox_manager=self.sandbox_mcp_server_manager(),
            lifecycle_event_repo=SqlMCPLifecycleEventRepository(self._db),
            project_repo=SqlProjectRepository(self._db),
            redis_client=self._redis_client,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    _logger = logging.getLogger(__name__)

    @staticmethod
    def _sandbox_application_services() -> SandboxApplicationServicesV2:
        from src.infrastructure.plugins.v2.sandbox_projection import (
            current_sandbox_application_services_v2,
        )

        return current_sandbox_application_services_v2()

    def _resolve_memstack_volume(self) -> dict[str, str] | None:
        """Resolve host_memstack_volume, auto-deriving the path when possible.

        Priority:
        1. Explicit ``SANDBOX_HOST_MEMSTACK_PATH`` setting (non-empty).
        2. Auto-derive from ``SANDBOX_HOST_SOURCE_PATH`` parent + ".memstack".
        3. Auto-derive from CWD + ".memstack" (development fallback).
        4. ``None`` -- no dedicated mount.
        """
        if not self._settings:
            return None

        mount_point = self._settings.sandbox_host_memstack_mount_point

        # 1. Explicit setting
        if self._settings.sandbox_host_memstack_path:
            return {self._settings.sandbox_host_memstack_path: mount_point}

        # 2. Derive from host source path
        if self._settings.sandbox_host_source_path:
            derived = Path(self._settings.sandbox_host_source_path).parent / ".memstack"
            if derived.is_dir():
                self._logger.debug(
                    "Auto-derived memstack volume from host_source_path: %s", derived
                )
                return {str(derived): mount_point}

        # 3. Derive from CWD (development fallback)
        cwd_memstack = Path.cwd() / ".memstack"
        if cwd_memstack.is_dir():
            self._logger.debug("Auto-derived memstack volume from CWD: %s", cwd_memstack)
            return {str(cwd_memstack): mount_point}

        return None

    def _resolve_docker_socket_volume(self) -> dict[str, str] | None:
        """Resolve optional Docker socket mount for sandbox Docker-aware tasks."""
        if not self._settings or not self._settings.sandbox_docker_socket_enabled:
            return None

        socket_path = Path(self._settings.sandbox_docker_socket_path)
        if not socket_path.exists():
            self._logger.warning(
                "SANDBOX_DOCKER_SOCKET_ENABLED=true but socket path does not exist: %s",
                socket_path,
            )
            return None

        return {str(socket_path): "/var/run/docker.sock"}

    def dependency_orchestrator(self) -> Any:
        """Get DependencyOrchestrator for sandbox dependency management.

        Coordinates dependency installation across host and sandbox runtimes.
        Requires redis_client and a pinned sandbox generation.
        """
        from src.infrastructure.agent.plugins.sandbox_deps.orchestrator import (
            DependencyOrchestrator,
        )
        from src.infrastructure.agent.plugins.sandbox_deps.sandbox_installer import (
            SandboxDependencyInstaller,
        )
        from src.infrastructure.agent.plugins.sandbox_deps.security_gate import SecurityGate
        from src.infrastructure.agent.plugins.sandbox_deps.state_store import DepsStateStore

        security_gate = SecurityGate()
        state_store = DepsStateStore(redis_client=self._redis_client)

        sandbox_adapter = self._sandbox_application_services().adapter

        sandbox_installer = SandboxDependencyInstaller(
            sandbox_tool_caller=cast(Any, sandbox_adapter).execute_tool,
            security_gate=security_gate,
        )

        return DependencyOrchestrator(
            state_store=state_store,
            sandbox_installer=sandbox_installer,
            security_gate=security_gate,
        )
