from abc import ABC, abstractmethod

from src.domain.model.workspace.workspace_agent import WorkspaceAgent


class WorkspaceAgentRepository(ABC):
    """Repository interface for workspace-bound agents."""

    @abstractmethod
    async def save(self, workspace_agent: WorkspaceAgent) -> WorkspaceAgent:
        """Save a workspace agent relation (create or update)."""

    @abstractmethod
    async def find_by_id(self, workspace_agent_id: str) -> WorkspaceAgent | None:
        """Find workspace agent relation by ID."""

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        active_only: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceAgent]:
        """List agents in a workspace."""

    @abstractmethod
    async def delete(self, workspace_agent_id: str) -> bool:
        """Delete workspace agent relation by ID."""
