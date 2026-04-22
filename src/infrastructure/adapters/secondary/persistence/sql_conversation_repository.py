"""
V2 SQLAlchemy implementation of ConversationRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements ConversationRepository interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods
- Implements PostgreSQL upsert (ON CONFLICT DO UPDATE) for efficient saves

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support

Key Features:
- Upsert operations using PostgreSQL ON CONFLICT
- save_and_commit for SSE streaming scenarios
- List by project/user with status filtering
- Efficient count operations
"""

import logging

from sqlalchemy import BigInteger, delete, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import Conversation, ConversationStatus
from src.domain.model.agent.agent_mode import AgentMode
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.merge_strategy import MergeStrategy
from src.domain.ports.repositories.agent_repository import ConversationRepository
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
    Conversation as DBConversation,
)

logger = logging.getLogger(__name__)


class SqlConversationRepository(
    BaseRepository[Conversation, DBConversation], ConversationRepository
):
    """
    V2 SQLAlchemy implementation of ConversationRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    conversation-specific query methods and upsert functionality.
    """

    # Define the SQLAlchemy model class
    _model_class = DBConversation

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (conversation-specific operations) ===

    async def save(self, conversation: Conversation) -> Conversation:
        """
        Save a conversation using PostgreSQL upsert (ON CONFLICT DO UPDATE).

        This is more efficient than SELECT then INSERT/UPDATE as it:
        - Eliminates N+1 query patterns
        - Uses a single database round-trip
        - Handles concurrent operations safely

        Args:
            conversation: Domain conversation entity to save
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
            "summary": conversation.summary,
            "fork_source_id": conversation.fork_source_id,
            "fork_context_snapshot": conversation.fork_context_snapshot,
            "merge_strategy": conversation.merge_strategy.value,
            # Multi-agent (Track B)
            "participant_agents": list(conversation.participant_agents),
            "conversation_mode": (
                conversation.conversation_mode.value
                if conversation.conversation_mode is not None
                else None
            ),
            "coordinator_agent_id": conversation.coordinator_agent_id,
            "focused_agent_id": conversation.focused_agent_id,
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
                    "summary": conversation.summary,
                    "fork_source_id": conversation.fork_source_id,
                    "fork_context_snapshot": conversation.fork_context_snapshot,
                    "merge_strategy": conversation.merge_strategy.value,
                    # Multi-agent (Track B)
                    "participant_agents": list(conversation.participant_agents),
                    "conversation_mode": (
                        conversation.conversation_mode.value
                        if conversation.conversation_mode is not None
                        else None
                    ),
                    "coordinator_agent_id": conversation.coordinator_agent_id,
                    "focused_agent_id": conversation.focused_agent_id,
                },
            )
        )

        await self._session.execute(refresh_select_statement(self._refresh_statement(stmt)))
        await self._session.flush()
        return conversation

    async def save_and_commit(self, conversation: Conversation) -> None:
        """
        Save a conversation and immediately commit to database.

        This is used for SSE streaming where conversations need to be visible
        to subsequent queries before the stream completes.

        Args:
            conversation: Domain conversation entity to save and commit
        """
        await self.save(conversation)
        logger.info(
            f"[save_and_commit] Committing conversation {conversation.id} with title: {conversation.title}"
        )
        await self._session.commit()
        logger.info(f"[save_and_commit] Commit successful for conversation {conversation.id}")

    async def list_by_project(
        self,
        project_id: str,
        status: ConversationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """
        List conversations for a project.

        Args:
            project_id: Project ID to filter by
            status: Optional status filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of conversations ordered by last activity time descending.
            Last activity is determined by the most recent event in agent_execution_events.
            Falls back to conversation created_at if no events exist.
        """
        last_activity_subq = (
            select(
                DBAgentExecutionEvent.conversation_id,
                func.max(DBAgentExecutionEvent.event_time_us).label("last_event_time_us"),
            )
            .group_by(DBAgentExecutionEvent.conversation_id)
            .subquery("last_activity")
        )

        query = (
            select(DBConversation)
            .outerjoin(
                last_activity_subq,
                DBConversation.id == last_activity_subq.c.conversation_id,
            )
            .where(DBConversation.project_id == project_id)
        )

        if status:
            query = query.where(DBConversation.status == status.value)

        # Sort by last event time (microseconds), falling back to created_at converted
        # to microseconds for consistent comparison with event_time_us.
        created_at_us = func.cast(
            func.extract("epoch", DBConversation.created_at) * 1_000_000,
            BigInteger,
        )
        query = (
            query.order_by(
                desc(func.coalesce(last_activity_subq.c.last_event_time_us, created_at_us))
            )
            .offset(offset)
            .limit(limit)
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_conversations = result.scalars().all()
        return [d for c in db_conversations if (d := self._to_domain(c)) is not None]

    async def list_by_user(
        self,
        user_id: str,
        project_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Conversation]:
        """
        List conversations for a user.

        Args:
            user_id: User ID to filter by
            project_id: Optional project ID filter
            limit: Maximum number of results
            offset: Number of results to skip

        Returns:
            List of conversations ordered by last activity time descending.
            Last activity is determined by the most recent event in agent_execution_events.
            Falls back to conversation created_at if no events exist.
        """
        last_activity_subq = (
            select(
                DBAgentExecutionEvent.conversation_id,
                func.max(DBAgentExecutionEvent.event_time_us).label("last_event_time_us"),
            )
            .group_by(DBAgentExecutionEvent.conversation_id)
            .subquery("last_activity")
        )

        query = (
            select(DBConversation)
            .outerjoin(
                last_activity_subq,
                DBConversation.id == last_activity_subq.c.conversation_id,
            )
            .where(DBConversation.user_id == user_id)
        )

        if project_id:
            query = query.where(DBConversation.project_id == project_id)

        created_at_us = func.cast(
            func.extract("epoch", DBConversation.created_at) * 1_000_000,
            BigInteger,
        )
        query = (
            query.order_by(
                desc(func.coalesce(last_activity_subq.c.last_event_time_us, created_at_us))
            )
            .offset(offset)
            .limit(limit)
        )

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        db_conversations = result.scalars().all()
        return [d for c in db_conversations if (d := self._to_domain(c)) is not None]

    async def delete(self, conversation_id: str) -> bool:
        """
        Delete a conversation by ID.

        Uses CASCADE delete - related messages and executions will be deleted automatically.

        Args:
            conversation_id: Conversation ID to delete
        """
        # Override to use direct delete instead of BaseRepository's delete
        # This ensures CASCADE works properly
        await self._session.execute(
            refresh_select_statement(
                self._refresh_statement(
                    delete(DBConversation).where(DBConversation.id == conversation_id)
                )
            )
        )
        await self._session.flush()
        return True

    async def count_by_project(
        self, project_id: str, status: ConversationStatus | None = None
    ) -> int:
        """
        Count conversations for a project.

        Args:
            project_id: Project ID to count conversations for
            status: Optional status filter

        Returns:
            Number of conversations
        """
        query = (
            select(func.count())
            .select_from(DBConversation)
            .where(DBConversation.project_id == project_id)
        )
        if status:
            query = query.where(DBConversation.status == status.value)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(query))
        )
        return result.scalar() or 0

    # === Conversion methods ===

    def _to_domain(self, db_conversation: DBConversation | None) -> Conversation | None:
        """
        Convert database model to domain model.

        Args:
            db_conversation: Database model instance or None

        Returns:
            Domain model instance or None
        """
        if db_conversation is None:
            return None

        # Multi-agent (Track B) — safe decode with defaults for legacy rows.
        mode_raw = getattr(db_conversation, "conversation_mode", None)
        conv_mode = ConversationMode(mode_raw) if mode_raw else None
        participant_agents = list(getattr(db_conversation, "participant_agents", None) or [])

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
            summary=db_conversation.summary,
            fork_source_id=db_conversation.fork_source_id,
            fork_context_snapshot=db_conversation.fork_context_snapshot,
            merge_strategy=MergeStrategy(db_conversation.merge_strategy)
            if db_conversation.merge_strategy
            else MergeStrategy.RESULT_ONLY,
            # Multi-agent
            participant_agents=participant_agents,
            conversation_mode=conv_mode,
            coordinator_agent_id=getattr(db_conversation, "coordinator_agent_id", None),
            focused_agent_id=getattr(db_conversation, "focused_agent_id", None),
        )

    def _to_db(self, domain_entity: Conversation) -> DBConversation:
        """
        Convert domain entity to database model.

        Note: The save() method uses custom upsert logic, so this is primarily
        used by the BaseRepository for internal operations.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBConversation(
            id=domain_entity.id,
            project_id=domain_entity.project_id,
            tenant_id=domain_entity.tenant_id,
            user_id=domain_entity.user_id,
            title=domain_entity.title,
            status=domain_entity.status.value,
            agent_config=domain_entity.agent_config,
            meta=domain_entity.metadata,
            message_count=domain_entity.message_count,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            current_mode=domain_entity.current_mode.value,
            current_plan_id=domain_entity.current_plan_id,
            parent_conversation_id=domain_entity.parent_conversation_id,
            summary=domain_entity.summary,
            fork_source_id=domain_entity.fork_source_id,
            fork_context_snapshot=domain_entity.fork_context_snapshot,
            merge_strategy=domain_entity.merge_strategy.value,
            # Multi-agent (Track B)
            participant_agents=list(domain_entity.participant_agents),
            conversation_mode=(
                domain_entity.conversation_mode.value
                if domain_entity.conversation_mode is not None
                else None
            ),
            coordinator_agent_id=domain_entity.coordinator_agent_id,
            focused_agent_id=domain_entity.focused_agent_id,
        )
