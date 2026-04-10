"""Application service for agent-to-agent session communication.

Enables agents to discover peer sessions, read their history,
and send messages within the same project scope.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.model.agent import (
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from src.domain.ports.repositories.agent_repository import (
    ConversationRepository,
    MessageRepository,
)

logger = logging.getLogger(__name__)


class SessionCommService:
    """Service for inter-session communication between agents.

    All operations are scoped by project_id for multi-tenant isolation.
    """

    def __init__(
        self,
        conversation_repo: ConversationRepository,
        message_repo: MessageRepository,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo

    async def list_sessions(
        self,
        project_id: str,
        *,
        exclude_conversation_id: str | None = None,
        status_filter: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List conversations (sessions) within the same project.

        Args:
            project_id: Project scope for multi-tenant isolation.
            exclude_conversation_id: Current conversation to exclude.
            status_filter: Optional status filter (active/archived).
            limit: Maximum results to return.
            offset: Pagination offset.

        Returns:
            List of session summary dicts.
        """
        status: ConversationStatus | None = None
        if status_filter:
            try:
                status = ConversationStatus(status_filter)
            except ValueError:
                logger.warning(
                    "Invalid status_filter '%s', ignoring",
                    status_filter,
                )

        conversations: list[Conversation] = await self._conversation_repo.list_by_project(
            project_id,
            status=status,
            limit=limit,
            offset=offset,
        )

        results: list[dict[str, Any]] = []
        for conv in conversations:
            if exclude_conversation_id and conv.id == exclude_conversation_id:
                continue
            results.append(conv.to_dict())

        return results

    async def get_session_history(
        self,
        project_id: str,
        target_conversation_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Retrieve message history from a target session.

        Args:
            project_id: Project scope for multi-tenant isolation.
            target_conversation_id: The conversation to read from.
            limit: Maximum messages to return.
            offset: Pagination offset.

        Returns:
            Dict with conversation metadata and messages.

        Raises:
            PermissionError: If the target conversation belongs
                to a different project.
            ValueError: If the target conversation does not exist.
        """
        conversation = await self._conversation_repo.find_by_id(
            target_conversation_id,
        )
        if conversation is None:
            raise ValueError(f"Conversation {target_conversation_id} not found")

        if conversation.project_id != project_id:
            raise PermissionError("Cannot access conversation from a different project")

        messages: list[Message] = await self._message_repo.list_by_conversation(
            target_conversation_id,
            limit=limit,
            offset=offset,
        )

        return {
            "conversation": conversation.to_dict(),
            "messages": [
                {
                    "id": msg.id,
                    "role": msg.role.value,
                    "content": msg.content,
                    "message_type": msg.message_type.value,
                    "created_at": msg.created_at.isoformat(),
                }
                for msg in messages
            ],
            "total": len(messages),
        }

    async def send_to_session(
        self,
        project_id: str,
        target_conversation_id: str,
        content: str,
        *,
        sender_conversation_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a message to another session within the same project.

        Args:
            project_id: Project scope for multi-tenant isolation.
            target_conversation_id: The conversation to send to.
            content: Message content.
            sender_conversation_id: Originating conversation ID
                (included in metadata).

        Returns:
            Dict with status and the created message ID.

        Raises:
            PermissionError: If the target conversation belongs
                to a different project.
            ValueError: If the target conversation does not exist or
                content is empty.
        """
        if not content.strip():
            raise ValueError("Message content cannot be empty")

        conversation = await self._conversation_repo.find_by_id(
            target_conversation_id,
        )
        if conversation is None:
            raise ValueError(f"Conversation {target_conversation_id} not found")

        if conversation.project_id != project_id:
            raise PermissionError("Cannot send to conversation in a different project")

        metadata: dict[str, Any] = {
            "source": "session_comm",
        }
        if sender_conversation_id:
            metadata["sender_conversation_id"] = sender_conversation_id

        message = Message(
            conversation_id=target_conversation_id,
            role=MessageRole.SYSTEM,
            content=content,
            message_type=MessageType.TEXT,
            metadata=metadata,
        )

        saved = await self._message_repo.save(message)
        logger.info(
            "session_comm: sent message %s to conversation %s",
            saved.id,
            target_conversation_id,
        )

        # Persist the conversation projection so sessions_history() returns
        # up-to-date message_count and updated_at.
        conversation.increment_message_count()
        await self._conversation_repo.save(conversation)

        return {
            "status": "sent",
            "message_id": saved.id,
            "target_conversation_id": target_conversation_id,
        }
