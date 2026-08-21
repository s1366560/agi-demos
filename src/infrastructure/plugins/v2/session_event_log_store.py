"""Ordered PostgreSQL store owned by the protocol-v2 session event-log service."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert

from src.infrastructure.adapters.secondary.persistence.agent_run_settlement import (
    apply_run_input_applied_projection,
)
from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
from src.infrastructure.adapters.secondary.persistence.models import AgentExecutionEvent
from src.infrastructure.adapters.secondary.persistence.sql_agent_execution_event_repository import (
    _sanitize_event_data_for_postgres,  # pyright: ignore[reportPrivateUsage]
    apply_conversation_event_projection_delta,
)
from src.infrastructure.agent.events.converter import normalize_event_dict

from .session_event_log_types import (
    SessionEventCursorV2,
    SessionEventRecordV2,
)

_SKIP_PERSIST_EVENT_TYPES = frozenset(
    {
        "thought_start",
        "thought_delta",
        "text_delta",
        "text_start",
    }
)
_MESSAGE_EVENT_TYPES = frozenset({"user_message", "assistant_message"})
_TERMINAL_WORKSPACE_STATUS_MESSAGES = {
    "goal_achieved:workspace_contract_submitted": "Workspace contract submitted.",
    "goal_achieved:workspace_terminal_report": "Workspace terminal report submitted.",
}


@dataclass(frozen=True, kw_only=True)
class _PersistableEvent:
    event_type: str
    event_data: dict[str, Any]
    cursor: SessionEventCursorV2


def _coerce_event_int(value: object, default: int = 0) -> int:
    try:
        return int(cast(Any, value))
    except (TypeError, ValueError):
        return default


def _sanitize_persistable_event(event: _PersistableEvent | None) -> _PersistableEvent | None:
    if event is None:
        return None
    return _PersistableEvent(
        event_type=event.event_type,
        event_data=dict(_sanitize_event_data_for_postgres(event.event_data)),
        cursor=event.cursor,
    )


def _terminal_workspace_status_event(
    event_data: dict[str, Any],
    *,
    cursor: SessionEventCursorV2,
    has_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool]:
    status = str(event_data.get("status", ""))
    content = _TERMINAL_WORKSPACE_STATUS_MESSAGES.get(status)
    if not content or has_assistant_message:
        return None, False
    return (
        _PersistableEvent(
            event_type="assistant_message",
            event_data={
                "content": content,
                "message_id": str(uuid.uuid4()),
                "role": "assistant",
                "source": "terminal_workspace_status",
                "status": status,
                "plugin_generation": event_data.get("plugin_generation"),
            },
            cursor=cursor,
        ),
        True,
    )


def _complete_event_for_persistence(
    raw_event_data: Mapping[str, Any],
    event_data: dict[str, Any],
    *,
    cursor: SessionEventCursorV2,
    has_text_end_messages: bool,
    has_complete_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool]:
    if not (has_text_end_messages or has_complete_assistant_message):
        content = str(event_data.get("content", "")).strip()
        has_completion_metadata = any(
            raw_event_data.get(field) for field in ("artifacts", "trace_url", "execution_summary")
        )
        if not (content or has_completion_metadata):
            return None, False
        complete_event_data: dict[str, Any] = {
            "content": content,
            "message_id": str(uuid.uuid4()),
            "role": "assistant",
            "source": "complete",
            "plugin_generation": event_data.get("plugin_generation"),
        }
        for field_name in ("artifacts", "trace_url", "execution_summary"):
            if raw_event_data.get(field_name):
                complete_event_data[field_name] = raw_event_data[field_name]
        return (
            _PersistableEvent(
                event_type="assistant_message",
                event_data=complete_event_data,
                cursor=cursor,
            ),
            True,
        )
    if has_text_end_messages:
        return (
            _PersistableEvent(
                event_type="complete",
                event_data=event_data,
                cursor=cursor,
            ),
            False,
        )
    return None, False


def _prepare_event_for_persistence(
    event: Mapping[str, Any],
    *,
    has_text_end_messages: bool,
    has_complete_assistant_message: bool,
) -> tuple[_PersistableEvent | None, bool, bool]:
    normalized_event = normalize_event_dict(event)
    if normalized_event is None:
        return None, has_text_end_messages, has_complete_assistant_message

    event_type = str(normalized_event.get("type", "unknown"))
    if event_type in _SKIP_PERSIST_EVENT_TYPES:
        return None, has_text_end_messages, has_complete_assistant_message

    raw_event_data = normalized_event.get("data", {})
    event_data = dict(raw_event_data)
    cursor = SessionEventCursorV2(
        event_time_us=_coerce_event_int(normalized_event.get("event_time_us", 0)),
        event_counter=_coerce_event_int(normalized_event.get("event_counter", 0)),
    )
    persistable_event: _PersistableEvent | None
    next_has_text_end_messages = has_text_end_messages
    next_has_complete_assistant_message = has_complete_assistant_message

    if event_type == "text_end":
        full_text = str(event_data.get("full_text", "")).strip()
        persistable_event = None
        if full_text:
            persistable_event = _PersistableEvent(
                event_type="assistant_message",
                event_data={
                    "content": full_text,
                    "message_id": str(uuid.uuid4()),
                    "role": "assistant",
                    "source": "text_end",
                    "plugin_generation": event_data.get("plugin_generation"),
                },
                cursor=cursor,
            )
            next_has_text_end_messages = True
    elif event_type == "complete":
        persistable_event, complete_created_message = _complete_event_for_persistence(
            raw_event_data,
            event_data,
            cursor=cursor,
            has_text_end_messages=has_text_end_messages,
            has_complete_assistant_message=has_complete_assistant_message,
        )
        if complete_created_message:
            next_has_complete_assistant_message = True
    elif event_type == "status":
        persistable_event, status_created_message = _terminal_workspace_status_event(
            event_data,
            cursor=cursor,
            has_assistant_message=(has_text_end_messages or has_complete_assistant_message),
        )
        if status_created_message:
            next_has_complete_assistant_message = True
        if persistable_event is None:
            persistable_event = _PersistableEvent(
                event_type=event_type,
                event_data=event_data,
                cursor=cursor,
            )
    else:
        persistable_event = _PersistableEvent(
            event_type=event_type,
            event_data=event_data,
            cursor=cursor,
        )

    return (
        _sanitize_persistable_event(persistable_event),
        next_has_text_end_messages,
        next_has_complete_assistant_message,
    )


class SqlSessionEventLogStoreV2:
    """PostgreSQL adapter for the authoritative ordered session log."""

    async def append_stream_events(
        self,
        *,
        conversation_id: str,
        message_id: str,
        events: list[dict[str, Any]],
        correlation_id: str | None,
    ) -> None:
        async with async_session_factory() as session, session.begin():
            existing_assistant_result = await session.execute(
                select(AgentExecutionEvent.event_data).where(
                    AgentExecutionEvent.conversation_id == conversation_id,
                    AgentExecutionEvent.message_id == message_id,
                    AgentExecutionEvent.event_type == "assistant_message",
                )
            )
            existing_assistant_events = list(existing_assistant_result.scalars().all())
            has_text_end_messages = any(
                event_data.get("source") == "text_end" for event_data in existing_assistant_events
            )
            has_complete_assistant_message = any(
                event_data.get("source") == "complete" for event_data in existing_assistant_events
            )
            inserted_message_count = 0
            latest_event_time_us = 0

            for event in events:
                (
                    persistable_event,
                    has_text_end_messages,
                    has_complete_assistant_message,
                ) = _prepare_event_for_persistence(
                    event,
                    has_text_end_messages=has_text_end_messages,
                    has_complete_assistant_message=has_complete_assistant_message,
                )
                if persistable_event is None:
                    continue

                stmt = (
                    insert(AgentExecutionEvent)
                    .values(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        message_id=message_id,
                        event_type=persistable_event.event_type,
                        event_data=persistable_event.event_data,
                        event_time_us=persistable_event.cursor.event_time_us,
                        event_counter=persistable_event.cursor.event_counter,
                        correlation_id=correlation_id,
                        created_at=datetime.now(UTC),
                    )
                    .on_conflict_do_nothing(
                        index_elements=[
                            "conversation_id",
                            "event_time_us",
                            "event_counter",
                        ]
                    )
                    .returning(
                        AgentExecutionEvent.event_type,
                        AgentExecutionEvent.event_time_us,
                    )
                )
                insert_result = await session.execute(stmt)
                inserted_row = insert_result.one_or_none()
                if inserted_row is None:
                    continue
                inserted_event_type, inserted_event_time = inserted_row
                if inserted_event_type in _MESSAGE_EVENT_TYPES:
                    inserted_message_count += 1
                if inserted_event_type == "run_input_applied":
                    _ = await apply_run_input_applied_projection(
                        session,
                        event_data=persistable_event.event_data,
                    )
                latest_event_time_us = max(
                    latest_event_time_us,
                    int(inserted_event_time),
                )

            await apply_conversation_event_projection_delta(
                session,
                conversation_id,
                inserted_message_count=inserted_message_count,
                latest_event_time_us=latest_event_time_us or None,
            )

    async def read_events(
        self,
        *,
        conversation_id: str,
        after: SessionEventCursorV2 | None,
        limit: int,
    ) -> list[SessionEventRecordV2]:
        statement = select(AgentExecutionEvent).where(
            AgentExecutionEvent.conversation_id == conversation_id
        )
        if after is not None:
            statement = statement.where(
                or_(
                    AgentExecutionEvent.event_time_us > after.event_time_us,
                    and_(
                        AgentExecutionEvent.event_time_us == after.event_time_us,
                        AgentExecutionEvent.event_counter > after.event_counter,
                    ),
                )
            )
        statement = statement.order_by(
            AgentExecutionEvent.event_time_us.asc(),
            AgentExecutionEvent.event_counter.asc(),
        ).limit(limit)

        async with async_session_factory() as session:
            result = await session.execute(statement)
            return [
                SessionEventRecordV2(
                    event_id=row.id,
                    conversation_id=row.conversation_id,
                    message_id=row.message_id or "",
                    event_type=row.event_type,
                    event_data=row.event_data or {},
                    cursor=SessionEventCursorV2(
                        event_time_us=row.event_time_us,
                        event_counter=row.event_counter,
                    ),
                )
                for row in result.scalars().all()
            ]

    async def last_cursor(self, *, conversation_id: str) -> SessionEventCursorV2:
        async with async_session_factory() as session:
            result = await session.execute(
                select(
                    AgentExecutionEvent.event_time_us,
                    AgentExecutionEvent.event_counter,
                )
                .where(AgentExecutionEvent.conversation_id == conversation_id)
                .order_by(
                    AgentExecutionEvent.event_time_us.desc(),
                    AgentExecutionEvent.event_counter.desc(),
                )
                .limit(1)
            )
            row = result.one_or_none()
            if row is None:
                return SessionEventCursorV2()
            return SessionEventCursorV2(
                event_time_us=int(row[0]),
                event_counter=int(row[1]),
            )


__all__ = ["SqlSessionEventLogStoreV2"]
