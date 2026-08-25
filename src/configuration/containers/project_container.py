"""DI sub-container for project domain."""

from collections.abc import Awaitable, Callable
from typing import Any, Never

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.workspace_message_service import WorkspaceMessageService
from src.domain.ports.repositories.user_repository import UserRepository
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

    def workspace_task_repository(self) -> WorkspaceTaskRepository:
        """Get WorkspaceTaskRepository for workspace task persistence."""
        legacy_workspace_runtime_retired("DI task repository")

    def workspace_task_session_attempt_repository(
        self,
    ) -> Never:
        """Reject the retired platform SQL Workspace attempt repository."""
        legacy_workspace_runtime_retired("DI attempt repository")

    def workspace_task_session_attempt_service(self) -> Never:
        """Reject the retired platform SQL Workspace attempt service."""
        legacy_workspace_runtime_retired("DI attempt service")

    def topology_repository(self) -> Never:
        """Reject the retired platform SQL Topology repository."""
        legacy_workspace_runtime_retired("DI topology repository")

    def workspace_message_repository(self) -> WorkspaceMessageRepository:
        legacy_workspace_runtime_retired("DI message repository")

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
