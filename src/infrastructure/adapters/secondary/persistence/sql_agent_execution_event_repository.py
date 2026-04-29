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
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import cast, override

from sqlalchemy import case, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecutionEvent
from src.domain.ports.repositories.agent_repository import AgentExecutionEventRepository
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
    Conversation as DBConversation,
)

logger = logging.getLogger(__name__)

_MESSAGE_EVENT_TYPES = ("user_message", "assistant_message")
type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]


def _sanitize_json_for_postgres(value: object) -> JsonValue:
    """Remove NUL bytes from JSON payloads before PostgreSQL JSON storage."""
    if isinstance(value, str):
        return value.replace("\x00", "[NUL]")
    if isinstance(value, list):
        return [_sanitize_json_for_postgres(item) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): _sanitize_json_for_postgres(item)
            for key, item in value.items()
        }
    return cast(JsonValue, value)


def _sanitize_event_data_for_postgres(value: object) -> dict[str, JsonValue]:
    sanitized = _sanitize_json_for_postgres(value)
    return sanitized if isinstance(sanitized, dict) else {}


async def apply_conversation_event_projection_delta(
    session: AsyncSession,
    conversation_id: str,
    *,
    inserted_message_count: int,
    latest_event_time_us: int | None,
) -> None:
    """Apply an atomic, monotonic conversation projection update."""
    values: dict[str, object] = {}

    if inserted_message_count > 0:
        values["message_count"] = DBConversation.message_count + inserted_message_count

    if latest_event_time_us:
        latest_event_at = datetime.fromtimestamp(latest_event_time_us / 1_000_000, tz=UTC)
        values["updated_at"] = case(
            (DBConversation.updated_at.is_(None), latest_event_at),
            else_=func.greatest(DBConversation.updated_at, latest_event_at),
        )

    if not values:
        return

    _ = await session.execute(
        refresh_select_statement(update(DBConversation).where(DBConversation.id == conversation_id).values(**values))
    )


class SqlAgentExecutionEventRepository(
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

    @override
    async def save(self, domain_entity: AgentExecutionEvent) -> AgentExecutionEvent:
        """Save an agent execution event with idempotency guarantee."""
        event_data = _sanitize_event_data_for_postgres(domain_entity.event_data)
        stmt = (
            insert(DBAgentExecutionEvent)
            .values(
                id=domain_entity.id,
                conversation_id=domain_entity.conversation_id,
                message_id=domain_entity.message_id,
                event_type=str(domain_entity.event_type),
                event_data=event_data,
                event_time_us=domain_entity.event_time_us,
                event_counter=domain_entity.event_counter,
                created_at=domain_entity.created_at,
            )
            .on_conflict_do_nothing(
                index_elements=["conversation_id", "event_time_us", "event_counter"]
            )
            .returning(
                DBAgentExecutionEvent.event_type,
                DBAgentExecutionEvent.event_time_us,
            )
        )
        insert_result = await self._session.execute(refresh_select_statement(self._refresh_statement(stmt)))
        inserted_row = insert_result.one_or_none()
        if inserted_row is not None:
            inserted_event_type, inserted_event_time_us = inserted_row
            await apply_conversation_event_projection_delta(
                self._session,
                domain_entity.conversation_id,
                inserted_message_count=1 if inserted_event_type in _MESSAGE_EVENT_TYPES else 0,
                latest_event_time_us=int(inserted_event_time_us),
            )
        await self._session.flush()
        return domain_entity

    @override
    async def save_and_commit(self, domain_entity: AgentExecutionEvent) -> None:
        """Save an event and commit immediately."""
        await self.save(domain_entity)
        await self._session.commit()

    @override
    async def save_batch(self, events: list[AgentExecutionEvent]) -> None:
        """Save multiple events efficiently with idempotency guarantee."""
        if not events:
            return

        values_list = [
            {
                "id": event.id,
                "conversation_id": event.conversation_id,
                "message_id": event.message_id,
                "event_type": str(event.event_type),
                "event_data": _sanitize_event_data_for_postgres(event.event_data),
                "event_time_us": event.event_time_us,
                "event_counter": event.event_counter,
                "created_at": event.created_at,
            }
            for event in events
        ]
        stmt = (
            insert(DBAgentExecutionEvent)
            .values(values_list)
            .on_conflict_do_nothing(
                index_elements=["conversation_id", "event_time_us", "event_counter"]
            )
            .returning(
                DBAgentExecutionEvent.conversation_id,
                DBAgentExecutionEvent.event_type,
                DBAgentExecutionEvent.event_time_us,
            )
        )
        insert_result = await self._session.execute(refresh_select_statement(self._refresh_statement(stmt)))
        projection_deltas: dict[str, dict[str, int]] = {}
        for conversation_id, event_type, event_time_us in insert_result.all():
            delta = projection_deltas.setdefault(
                str(conversation_id),
                {"inserted_message_count": 0, "latest_event_time_us": 0},
            )
            if event_type in _MESSAGE_EVENT_TYPES:
                delta["inserted_message_count"] += 1
            delta["latest_event_time_us"] = max(delta["latest_event_time_us"], int(event_time_us))

        for conversation_id, delta in projection_deltas.items():
            await apply_conversation_event_projection_delta(
                self._session,
                conversation_id,
                inserted_message_count=delta["inserted_message_count"],
                latest_event_time_us=delta["latest_event_time_us"] or None,
            )
        await self._session.flush()

    @override
    async def get_events(
        self,
        conversation_id: str,
        from_time_us: int = 0,
        from_counter: int = 0,
        limit: int = 1000,
        event_types: set[str] | None = None,
        before_time_us: int | None = None,
        before_counter: int | None = None,
    ) -> list[AgentExecutionEvent]:
        """Get events for a conversation with bidirectional pagination support."""
        from sqlalchemy import literal, tuple_

        # Base query - always filter by conversation_id
        query = select(DBAgentExecutionEvent).where(
            DBAgentExecutionEvent.conversation_id == conversation_id,
        )

        time_col = DBAgentExecutionEvent.event_time_us
        counter_col = DBAgentExecutionEvent.event_counter

        if before_time_us is not None:
            # Backward pagination
            before_counter_val = before_counter if before_counter is not None else 0
            query = query.where(
                tuple_(time_col, counter_col)
                < tuple_(literal(before_time_us), literal(before_counter_val))
            )

            if event_types:
                query = query.where(DBAgentExecutionEvent.event_type.in_(event_types))

            query = query.order_by(time_col.desc(), counter_col.desc()).limit(limit)

            result = await self._session.execute(refresh_select_statement(self._refresh_statement(query)))
            db_events = list(reversed(result.scalars().all()))
        else:
            # Forward pagination
            if from_time_us > 0 or from_counter > 0:
                query = query.where(
                    tuple_(time_col, counter_col)
                    > tuple_(literal(from_time_us), literal(from_counter))
                )

            if event_types:
                query = query.where(DBAgentExecutionEvent.event_type.in_(event_types))

            query = query.order_by(time_col.asc(), counter_col.asc()).limit(limit)

            result = await self._session.execute(refresh_select_statement(self._refresh_statement(query)))
            db_events = list(result.scalars().all())

        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def get_last_event_time(self, conversation_id: str) -> tuple[int, int]:
        """Get the last (event_time_us, event_counter) for a conversation."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(
                    DBAgentExecutionEvent.event_time_us,
                    DBAgentExecutionEvent.event_counter,
                )
                .where(DBAgentExecutionEvent.conversation_id == conversation_id)
                .order_by(
                    DBAgentExecutionEvent.event_time_us.desc(),
                    DBAgentExecutionEvent.event_counter.desc(),
                )
                .limit(1)
            ))
        )
        row = result.one_or_none()
        if row is None:
            return (0, 0)
        return (row[0], row[1])

    @override
    async def get_events_by_message(
        self,
        conversation_id: str,
        message_id: str,
    ) -> list[AgentExecutionEvent]:
        """Get all events for a specific message."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBAgentExecutionEvent)
                .where(
                    DBAgentExecutionEvent.conversation_id == conversation_id,
                    DBAgentExecutionEvent.message_id == message_id,
                )
                .order_by(
                    DBAgentExecutionEvent.event_time_us.asc(),
                    DBAgentExecutionEvent.event_counter.asc(),
                )
            ))
        )
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def get_events_by_message_ids(
        self,
        conversation_id: str,
        message_ids: set[str],
    ) -> dict[str, list[AgentExecutionEvent]]:
        """Get all events for multiple message IDs."""
        if not message_ids:
            return {}

        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBAgentExecutionEvent)
                .where(
                    DBAgentExecutionEvent.conversation_id == conversation_id,
                    DBAgentExecutionEvent.message_id.in_(message_ids),
                )
                .order_by(
                    DBAgentExecutionEvent.message_id.asc(),
                    DBAgentExecutionEvent.event_time_us.asc(),
                    DBAgentExecutionEvent.event_counter.asc(),
                )
            ))
        )

        events_by_message_id: dict[str, list[AgentExecutionEvent]] = {}
        for db_event in result.scalars().all():
            domain_event = self._to_domain(db_event)
            if domain_event is None or db_event.message_id is None:
                continue
            events_by_message_id.setdefault(db_event.message_id, []).append(domain_event)

        return events_by_message_id

    @override
    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all events for a conversation."""
        await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                delete(DBAgentExecutionEvent).where(
                    DBAgentExecutionEvent.conversation_id == conversation_id
                )
            ))
        )
        await self._session.flush()

    @override
    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 1000,
    ) -> list[AgentExecutionEvent]:
        """List all events for a conversation in chronological order."""
        return await self.get_events(
            conversation_id=conversation_id,
            from_time_us=0,
            limit=limit,
        )

    @override
    async def get_message_events(
        self,
        conversation_id: str,
        limit: int = 50,
    ) -> list[AgentExecutionEvent]:
        """Get message events (user_message + assistant_message) for LLM context."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBAgentExecutionEvent)
                .where(
                    DBAgentExecutionEvent.conversation_id == conversation_id,
                    DBAgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
                )
                .order_by(
                    DBAgentExecutionEvent.event_time_us.desc(),
                    DBAgentExecutionEvent.event_counter.desc(),
                )
                .limit(limit)
            ))
        )
        db_events = list(reversed(result.scalars().all()))
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def get_message_events_after(
        self,
        conversation_id: str,
        after_time_us: int,
        limit: int = 200,
    ) -> list[AgentExecutionEvent]:
        """Get message events after a given event_time_us cutoff."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(DBAgentExecutionEvent)
                .where(
                    DBAgentExecutionEvent.conversation_id == conversation_id,
                    DBAgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
                    DBAgentExecutionEvent.event_time_us > after_time_us,
                )
                .order_by(
                    DBAgentExecutionEvent.event_time_us.asc(),
                    DBAgentExecutionEvent.event_counter.asc(),
                )
                .limit(limit)
            ))
        )
        db_events = result.scalars().all()
        return [d for e in db_events if (d := self._to_domain(e)) is not None]

    @override
    async def count_messages(self, conversation_id: str) -> int:
        """Count message events in a conversation."""
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(
                select(func.count())
                .select_from(DBAgentExecutionEvent)
                .where(
                    DBAgentExecutionEvent.conversation_id == conversation_id,
                    DBAgentExecutionEvent.event_type.in_(["user_message", "assistant_message"]),
                )
            ))
        )
        return result.scalar() or 0

    # === Conversion methods ===

    @override
    def _to_domain(self, db_model: DBAgentExecutionEvent | None) -> AgentExecutionEvent | None:
        """Convert database model to domain model."""
        if db_model is None:
            return None

        return AgentExecutionEvent(
            id=db_model.id,
            conversation_id=db_model.conversation_id,
            message_id=db_model.message_id or "",
            event_type=db_model.event_type,
            event_data=_sanitize_event_data_for_postgres(db_model.event_data or {}),
            event_time_us=db_model.event_time_us,
            event_counter=db_model.event_counter,
            created_at=db_model.created_at,
        )

    @override
    def _to_db(self, domain_entity: AgentExecutionEvent) -> DBAgentExecutionEvent:
        """Convert domain entity to database model."""
        return DBAgentExecutionEvent(
            id=domain_entity.id,
            conversation_id=domain_entity.conversation_id,
            message_id=domain_entity.message_id,
            event_type=str(domain_entity.event_type),
            event_data=_sanitize_event_data_for_postgres(domain_entity.event_data),
            event_time_us=domain_entity.event_time_us,
            event_counter=domain_entity.event_counter,
            created_at=domain_entity.created_at,
        )

    @override
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
        db_model.event_data = _sanitize_event_data_for_postgres(domain_entity.event_data)
