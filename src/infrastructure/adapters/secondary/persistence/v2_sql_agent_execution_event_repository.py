"""
V2 SQLAlchemy implementation of AgentExecutionEventRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements AgentExecutionEventRepository interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support
"""

import logging
from typing import List, Optional, Set

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.domain.ports.repositories.agent_repository import AgentExecutionEventRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
)

logger = logging.getLogger(__name__)


class V2SqlAgentExecutionEventRepository(
    BaseRepository[AgentExecutionEvent, DBAgentExecutionEvent],
    AgentExecutionEventRepository,
):
    """
    V2 SQLAlchemy implementation of AgentExecutionEventRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    event-specific query methods.
    """

    # Define the SQLAlchemy model class
    _model_class = DBAgentExecutionEvent

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (event-specific queries) ===

    async def save(self, event: AgentExecutionEvent) -> None:
        """Save an agent execution event with idempotency guarantee."""
        stmt = (
            insert(DBAgentExecutionEvent)
            .values(
                id=event.id,
                conversation_id=event.conversation_id,
                message_id=event.message_id,
                event_type=str(event.event_type),
                event_data=event.event_data,
                sequence_number=event.sequence_number,
                created_at=event.created_at,
            )
            .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def save_and_commit(self, event: AgentExecutionEvent) -> None:
        """Save an event and commit immediately."""
        await self.save(event)
        await self._session.commit()

    async def save_batch(self, events: List[AgentExecutionEvent]) -> None:
        """Save multiple events efficiently with idempotency guarantee."""
        if not events:
            return

        values_list = [
            {
                "id": event.id,
                "conversation_id": event.conversation_id,
                "message_id": event.message_id,
                "event_type": str(event.event_type),
                "event_data": event.event_data,
                "sequence_number": event.sequence_number,
                "created_at": event.created_at,
            }
            for event in events
        ]
        stmt = (
            insert(DBAgentExecutionEvent)
            .values(values_list)
            .on_conflict_do_nothing(index_elements=["conversation_id", "sequence_number"])
        )
        await self._session.execute(stmt)
        await self._session.flush()

    async def get_events(
        self,
        conversation_id: str,
        from_sequence: int = 0,
        limit: int = 1000,
        event_types: Optional[Set[str]] = None,
        before_sequence: Optional[int] = None,
    ) -> List[AgentExecutionEvent]:
        """Get events for a conversation with bidirectional pagination support."""
        # Base query - always filter by conversation_id
        query = select(DBAgentExecutionEvent).where(
            DBAgentExecutionEvent.conversation_id == conversation_id,
        )

        if before_sequence is not None:
            # Backward pagination
            query = query.where(
                DBAgentExecutionEvent.sequence_number < before_sequence
            ).order_by(DBAgentExecutionEvent.sequence_number.desc()).limit(limit)

            if event_types:
                query = query.where(DBAgentExecutionEvent.event_type.in_(event_types))

            result = await self._session.execute(query)
            db_events = list(reversed(result.scalars().all()))
        else:
            # Forward pagination
            query = query.where(
                DBAgentExecutionEvent.sequence_number >= from_sequence
            )

            if event_types:
                query = query.where(DBAgentExecutionEvent.event_type.in_(event_types))

            query = query.order_by(DBAgentExecutionEvent.sequence_number.asc()).limit(limit)

            result = await self._session.execute(query)
            db_events = result.scalars().all()

        return [self._to_domain(e) for e in db_events]

    async def get_last_sequence(self, conversation_id: str) -> int:
        """Get the last sequence number for a conversation."""
        result = await self._session.execute(
            select(func.max(DBAgentExecutionEvent.sequence_number)).where(
                DBAgentExecutionEvent.conversation_id == conversation_id
            )
        )
        last_seq = result.scalar()
        return last_seq if last_seq is not None else 0

    async def get_events_by_message(
        self,
        message_id: str,
    ) -> List[AgentExecutionEvent]:
        """Get all events for a specific message."""
        result = await self._session.execute(
            select(DBAgentExecutionEvent)
            .where(DBAgentExecutionEvent.message_id == message_id)
            .order_by(DBAgentExecutionEvent.sequence_number.asc())
        )
        db_events = result.scalars().all()
        return [self._to_domain(e) for e in db_events]

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all events for a conversation."""
        await self._session.execute(
            delete(DBAgentExecutionEvent).where(
                DBAgentExecutionEvent.conversation_id == conversation_id
            )
        )
        await self._session.flush()

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 1000,
    ) -> List[AgentExecutionEvent]:
        """List all events for a conversation in sequence order."""
        return await self.get_events(
            conversation_id=conversation_id,
            from_sequence=0,
            limit=limit,
        )

    async def get_message_events(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> List[AgentExecutionEvent]:
        """Get message events (user_message + assistant_message) for LLM context."""
        # Query with DESC to get most recent messages, then reverse for chronological order
        result = await self._session.execute(
            select(DBAgentExecutionEvent)
            .where(
                DBAgentExecutionEvent.conversation_id == conversation_id,
                DBAgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
            )
            .order_by(DBAgentExecutionEvent.sequence_number.desc())
            .limit(limit)
        )
        db_events = list(reversed(result.scalars().all()))
        return [self._to_domain(e) for e in db_events]

    async def count_messages(self, conversation_id: str) -> int:
        """Count message events in a conversation."""
        result = await self._session.execute(
            select(func.count())
            .select_from(DBAgentExecutionEvent)
            .where(
                DBAgentExecutionEvent.conversation_id == conversation_id,
                DBAgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
            )
        )
        return result.scalar() or 0

    # === Conversion methods ===

    def _to_domain(self, db_event: Optional[DBAgentExecutionEvent]) -> Optional[AgentExecutionEvent]:
        """
        Convert database model to domain model.

        Args:
            db_event: Database model instance or None

        Returns:
            Domain model instance or None
        """
        if db_event is None:
            return None

        return AgentExecutionEvent(
            id=db_event.id,
            conversation_id=db_event.conversation_id,
            message_id=db_event.message_id,
            event_type=db_event.event_type,
            event_data=db_event.event_data or {},
            sequence_number=db_event.sequence_number,
            created_at=db_event.created_at,
        )

    def _to_db(self, domain_entity: AgentExecutionEvent) -> DBAgentExecutionEvent:
        """
        Convert domain entity to database model.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBAgentExecutionEvent(
            id=domain_entity.id,
            conversation_id=domain_entity.conversation_id,
            message_id=domain_entity.message_id,
            event_type=str(domain_entity.event_type),
            event_data=domain_entity.event_data,
            sequence_number=domain_entity.sequence_number,
            created_at=domain_entity.created_at,
        )

    def _update_fields(
        self, db_model: DBAgentExecutionEvent, domain_entity: AgentExecutionEvent
    ) -> None:
        """
        Update database model fields from domain entity.

        Args:
            db_model: Database model to update
            domain_entity: Domain entity with new values
        """
        db_model.event_type = str(domain_entity.event_type)
        db_model.event_data = domain_entity.event_data
