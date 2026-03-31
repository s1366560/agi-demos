"""DI sub-container for project domain."""

from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.blackboard_service import BlackboardService
from src.application.services.project_service import ProjectService
from src.application.services.tenant_service import TenantService
from src.application.services.topology_service import TopologyService
from src.application.services.workspace_message_service import WorkspaceMessageService
from src.domain.ports.repositories.project_repository import ProjectRepository
from src.domain.ports.repositories.tenant_repository import TenantRepository
from src.domain.ports.repositories.user_repository import UserRepository
from src.domain.ports.repositories.workspace.blackboard_repository import (
    BlackboardRepository,
)
from src.domain.ports.repositories.workspace.cyber_gene_repository import (
    CyberGeneRepository,
)
from src.domain.ports.repositories.workspace.cyber_objective_repository import (
    CyberObjectiveRepository,
)
from src.domain.ports.repositories.workspace.topology_repository import (
    TopologyRepository,
)
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_message_repository import (
    WorkspaceMessageRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import (
    WorkspaceRepository,
)
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_blackboard_repository import (
    SqlBlackboardRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cyber_gene_repository import (
    SqlCyberGeneRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_cyber_objective_repository import (
    SqlCyberObjectiveRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_project_repository import (
    SqlProjectRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_topology_repository import (
    SqlTopologyRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_agent_repository import (
    SqlWorkspaceAgentRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_member_repository import (
    SqlWorkspaceMemberRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_message_repository import (
    SqlWorkspaceMessageRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_repository import (
    SqlWorkspaceRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_workspace_task_repository import (
    SqlWorkspaceTaskRepository,
)


class ProjectContainer:
    """Sub-container for project-related services.

    Provides factory methods for project repository, project service,
    and tenant service. Cross-domain dependencies (user_repository,
    tenant_repository) are injected via callbacks.
    """

    def __init__(
        self,
        db: AsyncSession | None = None,
        user_repository_factory: Callable[[], UserRepository] | None = None,
        tenant_repository_factory: Callable[[], TenantRepository] | None = None,
    ) -> None:
        self._db = db
        self._user_repository_factory = user_repository_factory
        self._tenant_repository_factory = tenant_repository_factory

    def project_repository(self) -> ProjectRepository:
        """Get ProjectRepository for project persistence."""
        assert self._db is not None
        return SqlProjectRepository(self._db)

    def project_service(self) -> ProjectService:
        """Get ProjectService for project operations."""
        user_repo = self._user_repository_factory() if self._user_repository_factory else None
        assert user_repo is not None
        return ProjectService(
            project_repo=self.project_repository(),
            user_repo=user_repo,
        )

    def tenant_service(self) -> TenantService:
        """Get TenantService for tenant operations."""
        tenant_repo = self._tenant_repository_factory() if self._tenant_repository_factory else None
        user_repo = self._user_repository_factory() if self._user_repository_factory else None
        assert tenant_repo is not None
        assert user_repo is not None
        return TenantService(tenant_repo=tenant_repo, user_repo=user_repo)

    def workspace_repository(self) -> WorkspaceRepository:
        """Get WorkspaceRepository for workspace persistence."""
        assert self._db is not None
        return SqlWorkspaceRepository(self._db)

    def workspace_member_repository(self) -> WorkspaceMemberRepository:
        """Get WorkspaceMemberRepository for workspace membership persistence."""
        assert self._db is not None
        return SqlWorkspaceMemberRepository(self._db)

    def workspace_agent_repository(self) -> WorkspaceAgentRepository:
        """Get WorkspaceAgentRepository for workspace-agent relation persistence."""
        assert self._db is not None
        return SqlWorkspaceAgentRepository(self._db)

    def blackboard_repository(self) -> BlackboardRepository:
        """Get BlackboardRepository for workspace blackboard persistence."""
        assert self._db is not None
        return SqlBlackboardRepository(self._db)

    def blackboard_service(self) -> BlackboardService:
        """Get BlackboardService for blackboard post/reply operations."""
        return BlackboardService(
            blackboard_repo=self.blackboard_repository(),
            workspace_repo=self.workspace_repository(),
            workspace_member_repo=self.workspace_member_repository(),
        )

    def workspace_task_repository(self) -> WorkspaceTaskRepository:
        """Get WorkspaceTaskRepository for workspace task persistence."""
        assert self._db is not None
        return SqlWorkspaceTaskRepository(self._db)

    def topology_repository(self) -> TopologyRepository:
        """Get TopologyRepository for workspace topology persistence."""
        assert self._db is not None
        return SqlTopologyRepository(self._db)

    def topology_service(self) -> TopologyService:
        """Get TopologyService for workspace topology operations."""
        return TopologyService(
            workspace_repo=self.workspace_repository(),
            workspace_member_repo=self.workspace_member_repository(),
            topology_repo=self.topology_repository(),
            workspace_agent_repo=self.workspace_agent_repository(),
        )

    def cyber_objective_repository(self) -> CyberObjectiveRepository:
        assert self._db is not None
        return SqlCyberObjectiveRepository(self._db)

    def cyber_gene_repository(self) -> CyberGeneRepository:
        assert self._db is not None
        return SqlCyberGeneRepository(self._db)

    def workspace_message_repository(self) -> WorkspaceMessageRepository:
        assert self._db is not None
        return SqlWorkspaceMessageRepository(self._db)

    def workspace_message_service(
        self,
        workspace_event_publisher: (
            Callable[[str, str, dict[str, Any]], Awaitable[None]] | None
        ) = None,
    ) -> WorkspaceMessageService:
        """Get WorkspaceMessageService for chat message operations."""
        user_repo = self._user_repository_factory() if self._user_repository_factory else None
        return WorkspaceMessageService(
            message_repo=self.workspace_message_repository(),
            member_repo=self.workspace_member_repository(),
            agent_repo=self.workspace_agent_repository(),
            workspace_event_publisher=workspace_event_publisher,
            user_repo=user_repo,
        )
