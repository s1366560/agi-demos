from abc import ABC, abstractmethod

from src.domain.model.workspace.workspace_member import WorkspaceMember


class WorkspaceMemberRepository(ABC):
    """Repository interface for workspace membership."""

    @abstractmethod
    async def save(self, member: WorkspaceMember) -> WorkspaceMember:
        """Save a workspace member (create or update)."""

    @abstractmethod
    async def find_by_id(self, member_id: str) -> WorkspaceMember | None:
        """Find workspace member by ID."""

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceMember]:
        """List members in a workspace."""

    @abstractmethod
    async def find_by_workspace_and_user(
        self,
        workspace_id: str,
        user_id: str,
    ) -> WorkspaceMember | None:
        """Find a user's membership in a workspace."""

    @abstractmethod
    async def delete(self, member_id: str) -> bool:
        """Delete workspace member by ID."""
