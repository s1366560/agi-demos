"""Repository ports for graph orchestration entities."""

from abc import ABC, abstractmethod

from src.domain.model.agent.graph import AgentGraph, GraphRun


class AgentGraphRepository(ABC):
    """Repository port for AgentGraph aggregate root."""

    @abstractmethod
    async def save(self, domain_entity: AgentGraph) -> AgentGraph:
        """Persist an agent graph definition."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> AgentGraph | None:
        """Find a graph by its ID."""

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AgentGraph]:
        """List graphs for a project."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Soft-delete a graph by setting is_active=False."""

    @abstractmethod
    async def count_by_project(
        self,
        project_id: str,
        tenant_id: str,
        active_only: bool = True,
    ) -> int:
        """Count graphs for a project."""


class GraphRunRepository(ABC):
    """Repository port for GraphRun aggregate root."""

    @abstractmethod
    async def save(self, domain_entity: GraphRun) -> GraphRun:
        """Persist a graph run with its node executions."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> GraphRun | None:
        """Find a graph run by ID."""

    @abstractmethod
    async def list_by_graph(
        self,
        graph_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[GraphRun]:
        """List runs for a specific graph definition."""

    @abstractmethod
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[GraphRun]:
        """List runs associated with a conversation."""

    @abstractmethod
    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> GraphRun | None:
        """Find the currently active (non-terminal) run for a conversation."""

    @abstractmethod
    async def delete_by_graph(self, graph_id: str) -> None:
        """Delete all runs for a graph."""
