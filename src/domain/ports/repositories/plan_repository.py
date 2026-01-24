"""Repository port for Plan entities.

This module defines the repository interface for Plan Mode planning documents.
"""

from abc import ABC, abstractmethod
from typing import List, Optional

from src.domain.model.agent.plan import Plan, PlanDocumentStatus


class PlanRepository(ABC):
    """
    Repository port for Plan entities.

    Provides CRUD operations for Plan Mode planning documents
    with conversation scoping.
    """

    @abstractmethod
    async def save(self, plan: Plan) -> None:
        """
        Save a plan (create or update).

        Args:
            plan: The plan to save
        """
        pass

    @abstractmethod
    async def find_by_id(self, plan_id: str) -> Optional[Plan]:
        """
        Find a plan by its ID.

        Args:
            plan_id: The plan ID

        Returns:
            The plan if found, None otherwise
        """
        pass

    @abstractmethod
    async def find_by_conversation_id(
        self,
        conversation_id: str,
        status: Optional[PlanDocumentStatus] = None,
    ) -> List[Plan]:
        """
        Find all plans for a conversation.

        Args:
            conversation_id: The conversation ID
            status: Optional status filter

        Returns:
            List of plans for the conversation
        """
        pass

    @abstractmethod
    async def find_active_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[Plan]:
        """
        Find the active (non-archived) plan for a conversation.

        A conversation should have at most one active plan at a time.

        Args:
            conversation_id: The conversation ID

        Returns:
            The active plan if found, None otherwise
        """
        pass

    @abstractmethod
    async def list_by_project(
        self,
        project_id: str,
        status: Optional[PlanDocumentStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Plan]:
        """
        List plans for a project (across all conversations).

        Args:
            project_id: The project ID
            status: Optional status filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of plans
        """
        pass

    @abstractmethod
    async def list_by_user(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Plan]:
        """
        List plans created by a user.

        Args:
            user_id: The user ID
            project_id: Optional project ID filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of plans
        """
        pass

    @abstractmethod
    async def delete(self, plan_id: str) -> None:
        """
        Delete a plan by ID.

        Args:
            plan_id: The plan ID to delete
        """
        pass

    @abstractmethod
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """
        Delete all plans for a conversation.

        Args:
            conversation_id: The conversation ID
        """
        pass

    @abstractmethod
    async def count_by_conversation(self, conversation_id: str) -> int:
        """
        Count plans for a conversation.

        Args:
            conversation_id: The conversation ID

        Returns:
            Number of plans
        """
        pass

    @abstractmethod
    async def update_content(
        self,
        plan_id: str,
        content: str,
    ) -> Optional[Plan]:
        """
        Update plan content and increment version.

        Args:
            plan_id: The plan ID
            content: New content

        Returns:
            Updated plan if found, None otherwise
        """
        pass

    @abstractmethod
    async def update_status(
        self,
        plan_id: str,
        status: PlanDocumentStatus,
    ) -> Optional[Plan]:
        """
        Update plan status.

        Args:
            plan_id: The plan ID
            status: New status

        Returns:
            Updated plan if found, None otherwise
        """
        pass
