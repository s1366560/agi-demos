"""List conversations use case.

This use case handles listing conversations for a project.
"""

import logging
from typing import TYPE_CHECKING, List

if TYPE_CHECKING:
    from src.application.services.agent_service import AgentService

from src.domain.model.agent import Conversation, ConversationStatus

logger = logging.getLogger(__name__)


class ListConversationsUseCase:
    """Use case for listing conversations."""

    def __init__(self, agent_service: "AgentService"):
        """
        Initialize the use case.

        Args:
            agent_service: Agent service for business logic
        """
        self._agent_service = agent_service

    async def execute(
        self,
        project_id: str,
        user_id: str,
        limit: int = 50,
        status: ConversationStatus | None = None,
    ) -> List[Conversation]:
        """
        Execute the use case.

        Args:
            project_id: Project ID to filter by
            user_id: User ID to filter by
            limit: Maximum number of conversations to return
            status: Optional status filter

        Returns:
            List of conversation entities

        Raises:
            ValueError: if required parameters are missing
        """
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")

        conversations = await self._agent_service.list_conversations(
            project_id=project_id,
            user_id=user_id,
            limit=limit,
            status=status,
        )

        logger.info(f"Listed {len(conversations)} conversations for project {project_id}")

        return conversations
