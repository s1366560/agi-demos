"""
SQLAlchemy implementation of ConversationRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.ports.repositories.agent_repository import ConversationRepository
from src.infrastructure.adapters.secondary.persistence.models import Conversation as DBConversation

logger = logging.getLogger(__name__)


class SqlAlchemyConversationRepository(ConversationRepository):
    """SQLAlchemy implementation of ConversationRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, conversation: Conversation) -> None:
        """Save a conversation using PostgreSQL upsert (ON CONFLICT DO UPDATE).

        This is more efficient than SELECT then INSERT/UPDATE as it:
        - Eliminates N+1 query patterns
        - Uses a single database round-trip
        - Handles concurrent operations safely
        """
        # Build the values dictionary for upsert
        values = {
            "id": conversation.id,
            "project_id": conversation.project_id,
            "tenant_id": conversation.tenant_id,
            "user_id": conversation.user_id,
            "title": conversation.title,
            "status": conversation.status.value,
            "agent_config": conversation.agent_config,
            "meta": conversation.metadata,
            "message_count": conversation.message_count,
            "created_at": conversation.created_at,
            "updated_at": conversation.updated_at,
            "current_mode": conversation.current_mode.value,
            "current_plan_id": conversation.current_plan_id,
            "parent_conversation_id": conversation.parent_conversation_id,
        }

        # Use PostgreSQL ON CONFLICT for upsert
        stmt = (
            pg_insert(DBConversation)
            .values(**values)
            .on_conflict_do_update(
                index_elements=["id"],
                set_={
                    "title": conversation.title,
                    "status": conversation.status.value,
                    "agent_config": conversation.agent_config,
                    "meta": conversation.metadata,
                    "message_count": conversation.message_count,
                    "updated_at": conversation.updated_at,
                    "current_mode": conversation.current_mode.value,
                    "current_plan_id": conversation.current_plan_id,
                    "parent_conversation_id": conversation.parent_conversation_id,
                },
            )
        )

        await self._session.execute(stmt)
        await self._session.flush()

    async def save_and_commit(self, conversation: Conversation) -> None:
        """Save a conversation and immediately commit to database.

        This is used for SSE streaming where conversations need to be visible
        to subsequent queries before the stream completes.
        """
        await self.save(conversation)
        logger.info(
            f"[save_and_commit] Committing conversation {conversation.id} with title: {conversation.title}"
        )
        await self._session.commit()
        logger.info(f"[save_and_commit] Commit successful for conversation {conversation.id}")

    async def find_by_id(self, conversation_id: str) -> Optional[Conversation]:
        """Find a conversation by its ID."""
        result = await self._session.execute(
            select(DBConversation).where(DBConversation.id == conversation_id)
        )
        db_conversation = result.scalar_one_or_none()
        return self._to_domain(db_conversation) if db_conversation else None

    async def list_by_project(
        self,
        project_id: str,
        status: Optional[ConversationStatus] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        """List conversations for a project."""
        query = select(DBConversation).where(DBConversation.project_id == project_id)

        if status:
            query = query.where(DBConversation.status == status.value)

        query = query.order_by(desc(DBConversation.updated_at)).offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_conversations = result.scalars().all()
        return [self._to_domain(c) for c in db_conversations]

    async def list_by_user(
        self,
        user_id: str,
        project_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Conversation]:
        """List conversations for a user."""
        query = select(DBConversation).where(DBConversation.user_id == user_id)

        if project_id:
            query = query.where(DBConversation.project_id == project_id)

        query = query.order_by(desc(DBConversation.updated_at)).offset(offset).limit(limit)

        result = await self._session.execute(query)
        db_conversations = result.scalars().all()
        return [self._to_domain(c) for c in db_conversations]

    async def delete(self, conversation_id: str) -> None:
        """Delete a conversation by ID."""
        # Use CASCADE delete - related messages and executions will be deleted automatically
        await self._session.execute(
            delete(DBConversation).where(DBConversation.id == conversation_id)
        )
        await self._session.flush()

    async def count_by_project(self, project_id: str) -> int:
        """Count conversations for a project."""
        result = await self._session.execute(
            select(func.count())
            .select_from(DBConversation)
            .where(DBConversation.project_id == project_id)
        )
        return result.scalar() or 0

    @staticmethod
    def _to_domain(db_conversation: DBConversation) -> Conversation:
        """Convert database model to domain model."""
        from src.domain.model.agent.agent_mode import AgentMode

        return Conversation(
            id=db_conversation.id,
            project_id=db_conversation.project_id,
            tenant_id=db_conversation.tenant_id,
            user_id=db_conversation.user_id,
            title=db_conversation.title,
            status=ConversationStatus(db_conversation.status),
            agent_config=db_conversation.agent_config or {},
            metadata=db_conversation.meta or {},
            message_count=db_conversation.message_count,
            created_at=db_conversation.created_at,
            updated_at=db_conversation.updated_at,
            current_mode=AgentMode(db_conversation.current_mode)
            if db_conversation.current_mode
            else AgentMode.BUILD,
            current_plan_id=db_conversation.current_plan_id,
            parent_conversation_id=db_conversation.parent_conversation_id,
        )
