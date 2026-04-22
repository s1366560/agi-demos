"""Application service for agent-to-agent session communication.

Enables agents to discover peer sessions, read their history,
and send messages within the same project scope.
"""

from __future__ import annotations

import logging
from typing import Any

from src.domain.model.agent import (
    AgentExecutionEvent,
    Conversation,
    ConversationStatus,
    Message,
    MessageRole,
    MessageType,
)
from src.domain.ports.repositories.agent_repository import (
    AgentExecutionEventRepository,
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
        agent_execution_event_repo: AgentExecutionEventRepository | None = None,
    ) -> None:
        self._conversation_repo = conversation_repo
        self._message_repo = message_repo
        self._agent_execution_event_repo = agent_execution_event_repo

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

        fetch_count = max(limit + offset, conversation.message_count, 1)
        db_messages: list[Message] = await self._message_repo.list_by_conversation(
            target_conversation_id,
            limit=fetch_count,
            offset=0,
        )
        event_messages = await self._get_event_history(
            target_conversation_id,
            limit=fetch_count,
        )

        if event_messages:
            history_messages = [
                self._history_message_from_event(event) for event in event_messages
            ]
            history_messages.extend(
                self._history_message_from_message(message)
                for message in db_messages
                if message.role == MessageRole.SYSTEM
            )
        else:
            history_messages = [
                self._history_message_from_message(message) for message in db_messages
            ]

        history_messages.sort(key=lambda item: (item["created_at"], item["id"]))
        paged_messages = history_messages[offset : offset + limit]

        return {
            "conversation": conversation.to_dict(),
            "messages": paged_messages,
            "total": len(paged_messages),
        }

    async def _get_event_history(
        self,
        target_conversation_id: str,
        *,
        limit: int,
    ) -> list[AgentExecutionEvent]:
        """Read canonical user/assistant history from the event store when available."""
        if self._agent_execution_event_repo is None:
            return []
        return await self._agent_execution_event_repo.get_message_events(
            conversation_id=target_conversation_id,
            limit=limit,
        )

    @staticmethod
    def _history_message_from_message(message: Message) -> dict[str, str]:
        """Serialize a DB-backed message into sessions_history output shape."""
        return {
            "id": message.id,
            "role": message.role.value,
            "content": message.content,
            "message_type": message.message_type.value,
            "created_at": message.created_at.isoformat(),
        }

    @staticmethod
    def _history_message_from_event(event: AgentExecutionEvent) -> dict[str, str]:
        """Serialize a persisted message event into sessions_history output shape."""
        data = event.event_data
        role = str(
            data.get(
                "role",
                MessageRole.ASSISTANT.value if str(event.event_type) == "assistant_message" else MessageRole.USER.value,
            )
        )
        message_id = str(data.get("message_id") or event.message_id or event.id)
        return {
            "id": message_id,
            "role": role,
            "content": str(data.get("content", "")),
            "message_type": str(data.get("message_type", MessageType.TEXT.value)),
            "created_at": event.created_at.isoformat(),
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
        _ = conversation.increment_message_count()
        await self._conversation_repo.save(conversation)

        return {
            "status": "sent",
            "message_id": saved.id,
            "target_conversation_id": target_conversation_id,
        }
