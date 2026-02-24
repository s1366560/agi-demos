"""Service port for agent orchestration.

This module defines the AgentServicePort interface for orchestrating
React-mode agent execution with streaming support.
"""

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from src.domain.model.agent import Conversation


class AgentServicePort(ABC):
    """
    Port for agent orchestration service.

    This service manages the execution of React-mode agents,
    including conversation management and streaming responses.
    """

    @abstractmethod
    def stream_chat_v2(
        self,
        conversation_id: str,
        user_message: str,
        project_id: str,
        user_id: str,
        tenant_id: str,
        attachment_ids: list[str] | None = None,
        file_metadata: list[dict[str, Any]] | None = None,
        forced_skill_name: str | None = None,
        app_model_context: dict[str, Any] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """
        Stream agent response using self-developed ReAct core.

        This method yields events as the agent processes the user's message,
        allowing real-time feedback to the frontend with typewriter effect.

        Args:
            conversation_id: The conversation ID
            user_message: The user's message
            project_id: The project ID
            user_id: The user ID
            tenant_id: The tenant ID
            attachment_ids: Optional list of attachment IDs to include with the message

        Yields:
            Event dictionaries with type and data:
            - {"type": "thought", "data": {"thought": "..."}}
            - {"type": "act", "data": {"tool_name": "...", "tool_input": {...}}}
            - {"type": "observe", "data": {"observation": "...", "tool_output": "..."}}
            - {"type": "text_delta", "data": {"delta": "..."}}
            - {"type": "complete", "data": {"message_id": "...", "content": "..."}}
            - {"type": "error", "data": {"message": "..."}}
        """

    @abstractmethod
    async def get_available_tools(self, project_id: str, tenant_id: str) -> list[dict[str, Any]]:
        """
        Get list of available tools for the agent.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID

        Returns:
            List of tool definitions with name and description
        """

    @abstractmethod
    async def get_conversation_context(
        self,
        conversation_id: str,
        max_messages: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Get conversation context for agent processing.

        Args:
            conversation_id: The conversation ID
            max_messages: Maximum number of messages to include

        Returns:
            List of message dictionaries for LLM context
        """

    @abstractmethod
    async def create_conversation(
        self,
        project_id: str,
        user_id: str,
        tenant_id: str,
        title: str | None = None,
        agent_config: dict[str, Any] | None = None,
    ) -> Conversation:
        """
        Create a new conversation.

        Args:
            project_id: The project ID
            tenant_id: The tenant ID
            user_id: The user ID
            title: The conversation title
            agent_config: Optional agent configuration

        Returns:
            The created conversation
        """
