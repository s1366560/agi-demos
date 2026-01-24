"""
SQLAlchemy implementation of AgentExecutionEventRepository.
"""

import logging
from typing import List, Optional, Set

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.domain.ports.repositories.agent_repository import AgentExecutionEventRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
)

logger = logging.getLogger(__name__)


class SqlAlchemyAgentExecutionEventRepository(AgentExecutionEventRepository):
    """SQLAlchemy implementation of AgentExecutionEventRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, event: AgentExecutionEvent) -> None:
        """Save an agent execution event with idempotency guarantee.

        Uses INSERT ON CONFLICT DO NOTHING to handle Temporal retry scenarios
        where the same (conversation_id, sequence_number) may be inserted twice.
        """
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
        """Save multiple events efficiently with idempotency guarantee.

        Uses INSERT ON CONFLICT DO NOTHING to handle Temporal retry scenarios.
        """
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
    ) -> List[AgentExecutionEvent]:
        """Get events for a conversation starting from a sequence number.

        Args:
            conversation_id: The conversation ID
            from_sequence: Starting sequence number (inclusive)
            limit: Maximum number of events to return
            event_types: Optional set of event types to filter by. If None, returns all types.
        """
        query = select(DBAgentExecutionEvent).where(
            DBAgentExecutionEvent.conversation_id == conversation_id,
            DBAgentExecutionEvent.sequence_number >= from_sequence,
        )

        # Add event_types filter if specified
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
        """Get message events (user_message + assistant_message) for LLM context.

        Returns events ordered by sequence number (oldest first) for building
        conversation context. Uses DESC + reverse to get the most recent N messages.
        """
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

    @staticmethod
    def _to_domain(db_event: DBAgentExecutionEvent) -> AgentExecutionEvent:
        """Convert database model to domain model."""
        return AgentExecutionEvent(
            id=db_event.id,
            conversation_id=db_event.conversation_id,
            message_id=db_event.message_id,
            event_type=db_event.event_type,
            event_data=db_event.event_data or {},
            sequence_number=db_event.sequence_number,
            created_at=db_event.created_at,
        )
