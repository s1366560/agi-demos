"""
SQLAlchemy implementation of MessageRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Message
from src.domain.ports.repositories.agent_repository import MessageRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    Conversation as DBConversation,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Message as DBMessage,
)

logger = logging.getLogger(__name__)


class SqlAlchemyMessageRepository(MessageRepository):
    """SQLAlchemy implementation of MessageRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, message: Message) -> None:
        """Save a message using PostgreSQL upsert (ON CONFLICT DO UPDATE).

        This is more efficient than SELECT then INSERT/UPDATE as it:
        - Eliminates N+1 query patterns
        - Uses a single database round-trip
        - Handles concurrent operations safely
        """
        # Convert domain models to database format
        tool_calls_db = [
            {"name": tc.name, "arguments": tc.arguments, "call_id": tc.call_id}
            for tc in message.tool_calls
        ]
        tool_results_db = [
            {
                "tool_call_id": tr.tool_call_id,
                "result": tr.result,
                "is_error": tr.is_error,
                "error_message": tr.error_message,
            }
            for tr in message.tool_results
        ]

        # Build the values dictionary for upsert
        values = {
            "id": message.id,
            "conversation_id": message.conversation_id,
            "role": message.role.value,
            "content": message.content,
            "message_type": message.message_type.value,
            "tool_calls": tool_calls_db,
            "tool_results": tool_results_db,
            "meta": message.metadata,
            "created_at": message.created_at,
        }

        # Use PostgreSQL ON CONFLICT for upsert
        stmt = (
            pg_insert(DBMessage)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "role": message.role.value,
                    "content": message.content,
                    "message_type": message.message_type.value,
                    "tool_calls": tool_calls_db,
                    "tool_results": tool_results_db,
                    "meta": message.metadata,
                },
            )
        )

        await self._session.execute(stmt)
        await self._session.flush()

    async def save_and_commit(self, message: Message) -> None:
        """Save a message and immediately commit to database.

        This is used for SSE streaming where messages need to be visible
        to subsequent queries before the stream completes.
        """
        await self.save(message)
        await self._session.commit()

    async def find_by_id(self, message_id: str) -> Optional[Message]:
        """Find a message by its ID."""
        result = await self._session.execute(select(DBMessage).where(DBMessage.id == message_id))
        db_message = result.scalar_one_or_none()
        return self._to_domain(db_message) if db_message else None

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Message]:
        """List messages for a conversation in chronological order."""
        result = await self._session.execute(
            select(DBMessage)
            .where(DBMessage.conversation_id == conversation_id)
            .order_by(DBMessage.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        db_messages = result.scalars().all()
        return [self._to_domain(m) for m in db_messages]

    async def list_recent_by_project(
        self,
        project_id: str,
        limit: int = 10,
    ) -> List[Message]:
        """List recent messages across all conversations in a project."""
        result = await self._session.execute(
            select(DBMessage)
            .join(DBMessage.conversation)
            .where(DBConversation.project_id == project_id)
            .order_by(DBMessage.created_at.desc())
            .limit(limit)
        )
        db_messages = result.scalars().all()
        return [self._to_domain(m) for m in db_messages]

    async def count_by_conversation(self, conversation_id: str) -> int:
        """Count messages in a conversation."""
        result = await self._session.execute(
            select(func.count())
            .select_from(DBMessage)
            .where(DBMessage.conversation_id == conversation_id)
        )
        return result.scalar() or 0

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all messages in a conversation."""
        # CASCADE delete will handle related agent_executions
        await self._session.execute(
            delete(DBMessage).where(DBMessage.conversation_id == conversation_id)
        )
        await self._session.flush()

    @staticmethod
    def _to_domain(db_message: DBMessage) -> Message:
        """Convert database model to domain model."""
        from src.domain.model.agent import MessageRole, MessageType, ToolCall, ToolResult

        # Convert tool_calls from database format to domain
        tool_calls = [
            ToolCall(
                name=tc["name"],
                arguments=tc["arguments"],
                call_id=tc.get("call_id"),
            )
            for tc in (db_message.tool_calls or [])
        ]

        # Convert tool_results from database format to domain
        tool_results = [
            ToolResult(
                tool_call_id=tr["tool_call_id"],
                result=tr["result"],
                is_error=tr.get("is_error", False),
                error_message=tr.get("error_message"),
            )
            for tr in (db_message.tool_results or [])
        ]

        return Message(
            id=db_message.id,
            conversation_id=db_message.conversation_id,
            role=MessageRole(db_message.role),
            content=db_message.content,
            message_type=MessageType(db_message.message_type),
            tool_calls=tool_calls,
            tool_results=tool_results,
            metadata=db_message.meta or {},
            created_at=db_message.created_at,
        )
