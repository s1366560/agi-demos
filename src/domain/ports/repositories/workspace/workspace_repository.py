from abc import ABC, abstractmethod

from src.domain.model.workspace.workspace import Workspace


class WorkspaceRepository(ABC):
    """Repository interface for Workspace entity."""

    @abstractmethod
    async def save(self, workspace: Workspace) -> Workspace:
        """Save a workspace (create or update)."""

    @abstractmethod
    async def find_by_id(self, workspace_id: str) -> Workspace | None:
        """Find workspace by ID."""

    @abstractmethod
    async def find_by_project(
        self,
        tenant_id: str,
        project_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Workspace]:
        """List workspaces for a project under tenant scope."""

    @abstractmethod
    async def delete(self, workspace_id: str) -> bool:
        """Delete workspace by ID."""
