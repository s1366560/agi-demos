"""DI sub-container for project domain."""

from collections.abc import Callable
from typing import Never

from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.repositories.user_repository import UserRepository
from src.domain.ports.repositories.workspace.workspace_agent_repository import (
    WorkspaceAgentRepository,
)
from src.domain.ports.repositories.workspace.workspace_member_repository import (
    WorkspaceMemberRepository,
)
from src.domain.ports.repositories.workspace.workspace_repository import (
    WorkspaceRepository,
)
from src.infrastructure.workspace_core.legacy_runtime import legacy_workspace_runtime_retired


class ProjectContainer:
    """Legacy facade for workspace methods that have not moved to V2 yet."""

    def __init__(
        self,
        db: AsyncSession | None = None,
        user_repository_factory: Callable[[], UserRepository] | None = None,
    ) -> None:
        self._db = db
        self._user_repository_factory = user_repository_factory

    def workspace_repository(self) -> WorkspaceRepository:
        """Reject the retired platform SQL Workspace repository."""
        legacy_workspace_runtime_retired("DI workspace repository")

    def workspace_member_repository(self) -> WorkspaceMemberRepository:
        """Get WorkspaceMemberRepository for workspace membership persistence."""
        legacy_workspace_runtime_retired("DI member repository")

    def workspace_agent_repository(self) -> WorkspaceAgentRepository:
        """Get WorkspaceAgentRepository for workspace-agent relation persistence."""
        legacy_workspace_runtime_retired("DI agent repository")

    def topology_repository(self) -> Never:
        """Reject the retired platform SQL Topology repository."""
        legacy_workspace_runtime_retired("DI topology repository")
