"""WorkPlan repository port interface."""

from abc import ABC, abstractmethod

from src.domain.model.agent.work_plan import WorkPlan


class WorkPlanRepositoryPort(ABC):
    """Repository interface for WorkPlan entities."""

    @abstractmethod
    async def save(self, plan: WorkPlan) -> WorkPlan:
        """Save a work plan.

        Args:
            plan: The work plan to save

        Returns:
            The saved work plan
        """
        ...

    @abstractmethod
    async def get_by_id(self, plan_id: str) -> WorkPlan | None:
        """Get a work plan by its ID.

        Args:
            plan_id: The ID of the work plan

        Returns:
            The work plan if found, None otherwise
        """
        ...

    @abstractmethod
    async def get_by_conversation(self, conversation_id: str) -> list[WorkPlan]:
        """Get all work plans for a conversation.

        Args:
            conversation_id: The ID of the conversation

        Returns:
            List of work plans for the conversation
        """
        ...

    @abstractmethod
    async def get_active_by_conversation(self, conversation_id: str) -> WorkPlan | None:
        """Get the active (in-progress) work plan for a conversation.

        Args:
            conversation_id: The ID of the conversation

        Returns:
            The active work plan if found, None otherwise
        """
        ...

    @abstractmethod
    async def delete(self, plan_id: str) -> bool:
        """Delete a work plan.

        Args:
            plan_id: The ID of the work plan to delete

        Returns:
            True if deleted, False if not found
        """
        ...
