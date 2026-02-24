"""Get conversation use case.

This use case handles retrieving a single conversation.
"""

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.application.services.agent_service import AgentService

from src.domain.model.agent import Conversation

logger = logging.getLogger(__name__)


class GetConversationUseCase:
    """Use case for getting a conversation."""

    def __init__(self, agent_service: "AgentService") -> None:
        """
        Initialize the use case.

        Args:
            agent_service: Agent service for business logic
        """
        self._agent_service = agent_service

    async def execute(
        self,
        conversation_id: str,
        project_id: str,
        user_id: str,
    ) -> Conversation | None:
        """
        Execute the use case.

        Args:
            conversation_id: Conversation ID
            project_id: Project ID for authorization
            user_id: User ID for authorization

        Returns:
            Conversation entity or None if not found

        Raises:
            ValueError: if required parameters are missing
        """
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")

        conversation = await self._agent_service.get_conversation(
            conversation_id=conversation_id,
            project_id=project_id,
            user_id=user_id,
        )

        if conversation:
            logger.info(f"Retrieved conversation {conversation_id}")
        else:
            logger.warning(f"Conversation {conversation_id} not found")

        return conversation
