"""Create conversation use case.

This use case handles the creation of new conversations.
"""

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.application.services.agent_service import AgentService

from src.domain.model.agent import Conversation

logger = logging.getLogger(__name__)


class CreateConversationUseCase:
    """Use case for creating a new conversation."""

    def __init__(self, agent_service: "AgentService") -> None:
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
        tenant_id: str,
        title: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> Conversation:
        """
        Execute the use case.

        Args:
            project_id: Project ID for the conversation
            user_id: User ID who owns the conversation
            tenant_id: Tenant ID for multi-tenancy
            title: Optional title for the conversation
            agent_config: Optional agent configuration

        Returns:
            Created conversation entity

        Raises:
            ValueError: if required parameters are missing
        """
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        if not tenant_id:
            raise ValueError("tenant_id is required")

        conversation = await self._agent_service.create_conversation(
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
            title=title,
            agent_config=agent_config,
        )

        logger.info(
            f"Created conversation {conversation.id} for project {project_id}, user {user_id}"
        )

        return conversation
