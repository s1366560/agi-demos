"""Repository interface for AgentTask persistence."""

from abc import ABC, abstractmethod

from src.domain.model.agent.task import AgentTask


class AgentTaskRepository(ABC):
    """Repository port for agent task persistence.

    Tasks are scoped to conversations and managed by the agent
    via TodoRead/TodoWrite tools.
    """

    @abstractmethod
    async def save(self, task: AgentTask) -> None:
        """Save a single task (create or update)."""
        ...

    @abstractmethod
    async def save_all(self, conversation_id: str, tasks: list[AgentTask]) -> None:
        """Replace all tasks for a conversation (atomic)."""
        ...

    @abstractmethod
    async def find_by_conversation(
        self, conversation_id: str, status: str | None = None
    ) -> list[AgentTask]:
        """Find all tasks for a conversation, optionally filtered by status."""
        ...

    @abstractmethod
    async def find_by_id(self, task_id: str) -> AgentTask | None:
        """Find a task by ID."""
        ...

    @abstractmethod
    async def update(self, task_id: str, **fields) -> AgentTask | None:
        """Update specific fields on a task. Returns updated task or None."""
        ...

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all tasks for a conversation."""
        ...
