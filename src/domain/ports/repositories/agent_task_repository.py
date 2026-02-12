"""Repository interface for AgentTask persistence."""

from abc import ABC, abstractmethod
from typing import List, Optional

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
    async def save_all(self, conversation_id: str, tasks: List[AgentTask]) -> None:
        """Replace all tasks for a conversation (atomic)."""
        ...

    @abstractmethod
    async def find_by_conversation(
        self, conversation_id: str, status: Optional[str] = None
    ) -> List[AgentTask]:
        """Find all tasks for a conversation, optionally filtered by status."""
        ...

    @abstractmethod
    async def find_by_id(self, task_id: str) -> Optional[AgentTask]:
        """Find a task by ID."""
        ...

    @abstractmethod
    async def update(self, task_id: str, **fields) -> Optional[AgentTask]:
        """Update specific fields on a task. Returns updated task or None."""
        ...

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all tasks for a conversation."""
        ...
