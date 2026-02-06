"""DI sub-container for project domain."""

from typing import Callable, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.project_service import ProjectService
from src.application.services.tenant_service import TenantService
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.domain.ports.repositories.user_repository import UserRepository
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)


class ProjectContainer:
    """Sub-container for project-related services.

    Provides factory methods for project repository, project service,
    and tenant service. Cross-domain dependencies (user_repository,
    tenant_repository) are injected via callbacks.
    """

    def __init__(
        self,
        db: Optional[AsyncSession] = None,
        user_repository_factory: Optional[Callable[[], UserRepository]] = None,
        tenant_repository_factory: Optional[Callable[[], TenantRepository]] = None,
    ) -> None:
        self._db = db
        self._user_repository_factory = user_repository_factory
        self._tenant_repository_factory = tenant_repository_factory

    def project_repository(self) -> ProjectRepository:
        """Get ProjectRepository for project persistence."""
        return SqlProjectRepository(self._db)

    def project_service(self) -> ProjectService:
        """Get ProjectService for project operations."""
        user_repo = self._user_repository_factory() if self._user_repository_factory else None
        return ProjectService(
            project_repo=self.project_repository(),
            user_repo=user_repo,
        )

    def tenant_service(self) -> TenantService:
        """Get TenantService for tenant operations."""
        tenant_repo = self._tenant_repository_factory() if self._tenant_repository_factory else None
        user_repo = self._user_repository_factory() if self._user_repository_factory else None
        return TenantService(tenant_repo=tenant_repo, user_repo=user_repo)
