"""Chat use case.

This use case handles streaming chat interactions with the agent.
"""

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Dict

if TYPE_CHECKING:
    from src.application.services.agent_service import AgentService

logger = logging.getLogger(__name__)


class ChatUseCase:
    """Use case for streaming chat with the agent."""

    def __init__(self, agent_service: "AgentService"):
        """
        Initialize the use case.

        Args:
            agent_service: Agent service for business logic
        """
        self._agent_service = agent_service

    async def execute(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """
        Execute the use case.

        Args:
            conversation_id: Conversation ID
            user_message: User's message content
            project_id: Project ID
            user_id: User ID
            tenant_id: Tenant ID

        Yields:
            Event dictionaries with type and data:
            - {"type": "message", "data": {...}}
            - {"type": "thought", "data": {"thought": "..."}}
            - {"type": "act", "data": {"tool_name": "...", "tool_input": {...}}}
            - {"type": "observe", "data": {"observation": "..."}}
            - {"type": "complete", "data": {"content": "..."}}
            - {"type": "error", "data": {"message": "..."}}

        Raises:
            ValueError: if required parameters are missing
        """
        logger.info(
            f"[DEBUG-CHAT-0] execute() called with conversation_id={conversation_id}, user_message={user_message[:20]}"
        )
        if not conversation_id:
            raise ValueError("conversation_id is required")
        if not user_message:
            raise ValueError("user_message is required")
        if not project_id:
            raise ValueError("project_id is required")
        if not user_id:
            raise ValueError("user_id is required")
        if not tenant_id:
            raise ValueError("tenant_id is required")

        logger.info(
            f"Starting chat for conversation {conversation_id} "
            f"(user: {user_id}, project: {project_id})"
        )

        # Use self-developed ReAct core (v2) for all queries
        async for event in self._agent_service.stream_chat_v2(
            conversation_id=conversation_id,
            user_message=user_message,
            project_id=project_id,
            user_id=user_id,
            tenant_id=tenant_id,
        ):
            yield event

        logger.info(f"Completed chat for conversation {conversation_id}")
