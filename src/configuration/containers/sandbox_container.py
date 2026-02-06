"""DI sub-container for sandbox domain."""

from typing import Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.sandbox_orchestrator import SandboxOrchestrator
from src.domain.ports.services.sandbox_resource_port import SandboxResourcePort
from src.infrastructure.adapters.secondary.persistence.sql_project_sandbox_repository import (
    SqlProjectSandboxRepository,
)


class SandboxContainer:
    """Sub-container for sandbox-related services.

    Provides factory methods for sandbox repository, orchestrator,
    tool registry, resource, and lifecycle service.
    Cross-domain dependencies are injected via callbacks.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        redis_client=None,
        settings=None,
        sandbox_adapter_factory: Optional[Callable] = None,
        sandbox_event_publisher_factory: Optional[Callable] = None,
        distributed_lock_factory: Optional[Callable] = None,
    ) -> None:
        self._db = db
        self._redis_client = redis_client
        self._settings = settings
        self._sandbox_adapter_factory = sandbox_adapter_factory
        self._sandbox_event_publisher_factory = sandbox_event_publisher_factory
        self._distributed_lock_factory = distributed_lock_factory

    def project_sandbox_repository(self) -> SqlProjectSandboxRepository:
        """Get SqlProjectSandboxRepository for sandbox persistence."""
        return SqlProjectSandboxRepository(self._db)

    def sandbox_orchestrator(self) -> SandboxOrchestrator:
        """Get SandboxOrchestrator for unified sandbox service management."""
        sandbox_adapter = self._sandbox_adapter_factory() if self._sandbox_adapter_factory else None
        event_publisher = (
            self._sandbox_event_publisher_factory()
            if self._sandbox_event_publisher_factory
            else None
        )
        return SandboxOrchestrator(
            sandbox_adapter=sandbox_adapter,
            event_publisher=event_publisher,
            default_timeout=self._settings.sandbox_timeout_seconds if self._settings else 300,
        )

    def sandbox_tool_registry(self):
        """Get SandboxToolRegistry for dynamic MCP tool registration to Agent."""
        from src.application.services.sandbox_tool_registry import SandboxToolRegistry

        sandbox_adapter = self._sandbox_adapter_factory() if self._sandbox_adapter_factory else None
        return SandboxToolRegistry(
            redis_client=self._redis_client,
            mcp_adapter=sandbox_adapter,
        )

    def sandbox_resource(self) -> SandboxResourcePort:
        """Get SandboxResourcePort for agent workflow sandbox access."""
        from src.application.services.unified_sandbox_service import UnifiedSandboxService

        sandbox_adapter = self._sandbox_adapter_factory() if self._sandbox_adapter_factory else None
        distributed_lock = (
            self._distributed_lock_factory() if self._distributed_lock_factory else None
        )
        return UnifiedSandboxService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=sandbox_adapter,
            distributed_lock=distributed_lock,
            default_profile=self._settings.sandbox_profile_type if self._settings else "basic",
            health_check_interval_seconds=60,
            auto_recover=True,
        )

    def project_sandbox_lifecycle_service(self):
        """Get ProjectSandboxLifecycleService for project-dedicated sandbox management."""
        from src.application.services.project_sandbox_lifecycle_service import (
            ProjectSandboxLifecycleService,
        )

        sandbox_adapter = self._sandbox_adapter_factory() if self._sandbox_adapter_factory else None
        distributed_lock = (
            self._distributed_lock_factory() if self._distributed_lock_factory else None
        )
        return ProjectSandboxLifecycleService(
            repository=self.project_sandbox_repository(),
            sandbox_adapter=sandbox_adapter,
            distributed_lock=distributed_lock,
            default_profile=self._settings.sandbox_profile_type if self._settings else "basic",
            health_check_interval_seconds=60,
            auto_recover=True,
        )
