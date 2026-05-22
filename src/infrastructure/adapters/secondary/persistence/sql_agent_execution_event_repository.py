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
import re
import uuid
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
    PlanNodeModel,
    WorkspacePlanEventModel,
)

logger = logging.getLogger(__name__)

_MESSAGE_EVENT_TYPES = ("user_message", "assistant_message")
_WORKSPACE_PROGRESS_SOURCE_EVENT_TYPES = frozenset(
    {"assistant_message", "act", "observe", "error", "complete"}
)
_WORKSPACE_PROGRESS_NOTE_MAX = 320
_WORKSPACE_PROGRESS_MARKER_CONTEXT = 180
_WORKSPACE_PROGRESS_MARKER_LEAD = 80
_NOOP_OBSERVATIONS = frozenset({"(no output)", "no output"})
_LOW_SIGNAL_OBSERVATION_TOOLS = frozenset(
    {"edit", "glob", "grep", "read", "workspace_report_progress", "write"}
)
_LOW_SIGNAL_BASH_OBSERVATIONS = frozenset(
    {
        "finished",
        "killed",
        "killed old servers 000port free",
        "stopped old processes",
        "to address all issues, run: npm audit fix run `npm audit` for details.",
    }
)
_HIGH_SIGNAL_BASH_MARKERS = frozenset(
    {
        "=== SUMMARY ===",
        "DEPENDENCIES_VALIDATED",
        "First Load JS shared by all",
        "INSTALLATION_COMPLETE",
        "Route Status Report",
        "Routes returning 200",
        "[HTTP404]",
        "[OK]",
    }
)
_WORKSPACE_HARNESS_HEARTBEAT_MARKER = "[workspace_harness_heartbeat]"
_PROGRESS_ERROR_MARKERS = (
    "failed to compile",
    "type error",
    "error occurred",
    "should be wrapped",
    "exit code",
    "traceback",
)
type JsonValue = str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]

_JWT_PATTERN = re.compile(
    r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"
)
_MEMSTACK_API_KEY_PATTERN = re.compile(r"\bms_sk_[A-Za-z0-9_-]{32,}\b")
_BEARER_TOKEN_PATTERN = re.compile(r"(?i)\b(Bearer\s+)[A-Za-z0-9._~+/=-]{20,}")


def _redact_sensitive_text(value: str) -> str:
    redacted = value.replace("\x00", "[NUL]")
    redacted = _JWT_PATTERN.sub("[REDACTED_JWT]", redacted)
    redacted = _MEMSTACK_API_KEY_PATTERN.sub("[REDACTED_API_KEY]", redacted)
    return _BEARER_TOKEN_PATTERN.sub(r"\1[REDACTED_TOKEN]", redacted)


def _sanitize_json_for_postgres(value: object) -> JsonValue:
    """Remove unsafe bytes and secrets from JSON payloads before PostgreSQL storage."""
    if isinstance(value, str):
        return _redact_sensitive_text(value)
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
            (DBConversation.updated_at < latest_event_at, latest_event_at),
            else_=DBConversation.updated_at,
        )

    if not values:
        return

    _ = await session.execute(
        refresh_select_statement(update(DBConversation).where(DBConversation.id == conversation_id).values(**values))
    )


async def apply_workspace_event_progress_projection(
    session: AsyncSession,
    *,
    conversation_id: str,
    event_id: str,
    event_type: str,
    event_data: Mapping[str, JsonValue],
    event_time_us: int | None,
    created_at: datetime,
) -> None:
    """Mirror live workspace agent events into the durable plan progress surface."""
    if event_type not in _WORKSPACE_PROGRESS_SOURCE_EVENT_TYPES:
        return
    summary = _workspace_progress_summary(event_type, event_data)
    if not summary:
        return

    try:
        async with session.begin_nested():
            await _apply_workspace_event_progress_projection(
                session,
                conversation_id=conversation_id,
                event_id=event_id,
                event_type=event_type,
                event_time_us=event_time_us,
                created_at=created_at,
                summary=summary,
            )
    except Exception:
        logger.warning(
            "Failed to project workspace agent event progress "
            "(conversation_id=%s event_id=%s event_type=%s)",
            conversation_id,
            event_id,
            event_type,
            exc_info=True,
        )


async def _apply_workspace_event_progress_projection(
    session: AsyncSession,
    *,
    conversation_id: str,
    event_id: str,
    event_type: str,
    event_time_us: int | None,
    created_at: datetime,
    summary: str,
) -> None:
    conversation = await _workspace_projection_conversation(session, conversation_id)
    if conversation is None:
        return
    conversation_meta = _mapping_or_empty(conversation.meta)
    workspace_id = _string_or_none(conversation.workspace_id) or _string_or_none(
        conversation_meta.get("workspace_id")
    )
    task_id = _string_or_none(conversation.linked_workspace_task_id) or _string_or_none(
        conversation_meta.get("linked_workspace_task_id")
        or conversation_meta.get("workspace_task_id")
    )
    if not workspace_id or not task_id:
        return

    attempt_id = _string_or_none(
        conversation_meta.get("attempt_id") or conversation_meta.get("current_attempt_id")
    )
    node = await _workspace_projection_node(
        session,
        task_id=task_id,
        attempt_id=attempt_id,
    )
    if node is None:
        return

    node_metadata = dict(node.metadata_json or {})
    if node_metadata.get("latest_agent_event_progress_id") == event_id:
        return

    now = _aware_datetime(created_at)
    existing_progress = dict(node.progress or {})
    percent = _bounded_percent(existing_progress.get("percent"))
    actor_id = _workspace_projection_actor_id(conversation, conversation_meta)
    progress_event = {
        "event_type": "worker_progress",
        "source": "agent_execution_event_projection",
        "source_event_id": event_id,
        "source_event_type": event_type,
        "source_conversation_id": conversation_id,
        "source_event_time_us": event_time_us,
        "workspace_task_id": task_id,
        "attempt_id": attempt_id or node.current_attempt_id,
        "actor_id": actor_id,
        "phase": event_type,
        "percent": percent,
        "summary": summary,
        "created_at": now.isoformat(),
    }

    progress_events = node_metadata.get("progress_events")
    if not isinstance(progress_events, list):
        progress_events = []
    progress_events.append(progress_event)
    node_metadata["progress_events"] = progress_events[-25:]
    node_metadata["latest_agent_event_progress_id"] = event_id
    if _should_promote_workspace_progress_note(event_type, existing_progress, node_metadata):
        node.progress = {
            "percent": percent,
            "confidence": _bounded_confidence(existing_progress.get("confidence")),
            "note": summary,
        }
        node_metadata["latest_worker_progress"] = progress_event
    node.metadata_json = node_metadata
    node.updated_at = now

    session.add(
        WorkspacePlanEventModel(
            id=str(uuid.uuid4()),
            plan_id=node.plan_id,
            workspace_id=workspace_id,
            node_id=node.id,
            attempt_id=progress_event["attempt_id"],
            event_type="worker_progress",
            source="agent_execution_event_projection",
            actor_id=actor_id,
            payload_json=progress_event,
            created_at=now,
        )
    )


async def _workspace_projection_conversation(
    session: AsyncSession,
    conversation_id: str,
) -> DBConversation | None:
    result = await session.execute(
        refresh_select_statement(
            select(DBConversation).where(DBConversation.id == conversation_id)
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return None
    meta = _mapping_or_empty(conversation.meta)
    if not _string_or_none(conversation.workspace_id) and not _string_or_none(
        meta.get("workspace_id")
    ):
        return None
    return conversation


async def _workspace_projection_node(
    session: AsyncSession,
    *,
    task_id: str,
    attempt_id: str | None,
) -> PlanNodeModel | None:
    base_stmt = select(PlanNodeModel).where(PlanNodeModel.workspace_task_id == task_id)
    if attempt_id:
        result = await session.execute(
            refresh_select_statement(
                base_stmt.where(PlanNodeModel.current_attempt_id == attempt_id)
                .order_by(PlanNodeModel.updated_at.desc(), PlanNodeModel.created_at.desc())
                .limit(1)
            )
        )
        node = result.scalar_one_or_none()
        if node is not None:
            return node
    result = await session.execute(
        refresh_select_statement(
            base_stmt.order_by(
                PlanNodeModel.updated_at.desc(),
                PlanNodeModel.created_at.desc(),
            ).limit(1)
        )
    )
    return result.scalar_one_or_none()


def _workspace_projection_actor_id(
    conversation: DBConversation,
    metadata: Mapping[str, object],
) -> str | None:
    agent_config = _mapping_or_empty(conversation.agent_config)
    return _string_or_none(
        agent_config.get("selected_agent_id")
        or metadata.get("selected_agent_id")
        or metadata.get("agent_id")
    )


def _workspace_progress_summary(
    event_type: str,
    event_data: Mapping[str, JsonValue],
) -> str:
    summary = ""
    if event_type == "assistant_message":
        summary = (
            _string_or_none(event_data.get("content"))
            or _string_or_none(event_data.get("full_text"))
            or ""
        )
    elif event_type == "act":
        tool_name = _string_or_none(event_data.get("tool_name")) or "tool"
        summary = f"Running tool: {tool_name}"
    elif event_type == "observe":
        tool_name = _string_or_none(event_data.get("tool_name")) or "tool"
        status = _string_or_none(event_data.get("status")) or "completed"
        error = _string_or_none(event_data.get("error"))
        observation = _string_or_none(
            event_data.get("observation") or event_data.get("result")
        )
        if not error and (
            _is_noop_observation(observation)
            or _is_low_signal_observation(tool_name=tool_name, observation=observation)
        ):
            return ""
        heartbeat_summary = _workspace_harness_heartbeat_summary(
            tool_name=tool_name,
            observation=observation,
        )
        detail = error or heartbeat_summary or observation or ""
        if detail:
            status_label = "running" if not error and heartbeat_summary else status
            summary = f"{tool_name} {status_label}: {detail}"
        else:
            summary = f"{tool_name} {status}"
    elif event_type == "error":
        summary = (
            _string_or_none(event_data.get("message"))
            or _string_or_none(event_data.get("error"))
            or "Worker reported an error."
        )
    elif event_type == "complete":
        summary = (
            _string_or_none(event_data.get("content"))
            or _string_or_none(event_data.get("result"))
            or "Agent turn completed."
        )
    return _trim_progress_text(summary)


def _should_promote_workspace_progress_note(
    event_type: str,
    existing_progress: Mapping[str, object],
    node_metadata: Mapping[str, object],
) -> bool:
    if event_type != "act":
        return True
    existing_note = _string_or_none(existing_progress.get("note"))
    latest_progress = _mapping_or_empty(node_metadata.get("latest_worker_progress"))
    latest_event_type = _string_or_none(latest_progress.get("source_event_type"))
    return not existing_note or latest_event_type in {None, "act"}


def _trim_progress_text(value: str) -> str:
    collapsed = " ".join(str(value or "").split())
    if len(collapsed) <= _WORKSPACE_PROGRESS_NOTE_MAX:
        return collapsed
    marker_index = _progress_focus_index(collapsed)
    if marker_index > _WORKSPACE_PROGRESS_NOTE_MAX:
        prefix = collapsed[: _WORKSPACE_PROGRESS_NOTE_MAX - _WORKSPACE_PROGRESS_MARKER_CONTEXT - 8]
        detail = collapsed[
            marker_index : marker_index + _WORKSPACE_PROGRESS_MARKER_CONTEXT
        ]
        return f"{prefix.rstrip()} ... {detail.rstrip()}..."
    return f"{collapsed[: _WORKSPACE_PROGRESS_NOTE_MAX - 3].rstrip()}..."


def _progress_focus_index(value: str) -> int:
    lowered = value.casefold()
    indexes = [lowered.rfind(marker) for marker in _PROGRESS_ERROR_MARKERS]
    marker_index = max(indexes)
    if marker_index < 0:
        return -1
    return max(0, marker_index - _WORKSPACE_PROGRESS_MARKER_LEAD)


def _is_noop_observation(value: str | None) -> bool:
    if value is None:
        return True
    return " ".join(value.split()).casefold() in _NOOP_OBSERVATIONS


def _is_low_signal_observation(*, tool_name: str, observation: str | None) -> bool:
    if tool_name in _LOW_SIGNAL_OBSERVATION_TOOLS:
        return True
    if tool_name == "bash" and _has_high_signal_bash_marker(observation):
        return False
    return tool_name == "bash" and (
        _looks_like_plain_listing(observation) or _is_low_signal_bash_observation(observation)
    )


def _has_high_signal_bash_marker(value: str | None) -> bool:
    if not value:
        return False
    return any(marker in value for marker in _HIGH_SIGNAL_BASH_MARKERS)


def _workspace_harness_heartbeat_summary(
    *,
    tool_name: str,
    observation: str | None,
) -> str | None:
    if tool_name != "bash" or not _is_workspace_harness_heartbeat(observation):
        return None
    if observation is None:
        return None
    if _progress_focus_index(observation) >= 0 or _has_high_signal_bash_marker(
        observation
    ):
        return None
    return "command still running (workspace harness heartbeat)"


def _is_workspace_harness_heartbeat(value: str | None) -> bool:
    return bool(value and _WORKSPACE_HARNESS_HEARTBEAT_MARKER in value)


def _is_low_signal_bash_observation(value: str | None) -> bool:
    if not value:
        return False
    normalized = " ".join(value.split()).casefold()
    return (
        _is_pure_workspace_harness_heartbeat(normalized)
        or re.fullmatch(r"(?:[a-z0-9_-]+\s+)?(?:pid=)?\d+", normalized) is not None
        or (
            normalized.startswith("tool execution failed ")
            and normalized.endswith("(no output)")
        )
        or ".next/build_id" in normalized
        or _looks_like_search_result_listing(value)
        or normalized in _LOW_SIGNAL_BASH_OBSERVATIONS
    )


def _is_pure_workspace_harness_heartbeat(normalized: str) -> bool:
    heartbeat = _WORKSPACE_HARNESS_HEARTBEAT_MARKER.casefold()
    remainder = normalized.replace(heartbeat, "").replace("bash command still running", "")
    return not remainder.strip()


def _looks_like_search_result_listing(value: str | None) -> bool:
    if not value:
        return False
    if _progress_focus_index(value) >= 0 or _has_high_signal_bash_marker(value):
        return False
    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if len(lines) < 3:
        return False
    sample = lines[:12]
    matches = sum(
        1
        for line in sample
        if re.match(r"^\d+:", line)
        or re.match(r"^(?:[./A-Za-z0-9_@+-]+/)+[^:\s]+[-:]\d+[-:]", line)
    )
    return matches >= min(3, len(sample))


def _looks_like_plain_listing(value: str | None) -> bool:
    if not value:
        return False
    tokens = value.split()
    if len(tokens) < 2:
        return False
    return all(re.fullmatch(r"[A-Za-z0-9._@+-]+", token) for token in tokens)


def _string_or_none(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _mapping_or_empty(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _bounded_percent(value: object) -> float:
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        numeric = 0.0
    return max(0.0, min(100.0, numeric))


def _bounded_confidence(value: object) -> float:
    try:
        numeric = float(str(value))
    except (TypeError, ValueError):
        numeric = 1.0
    return max(0.0, min(1.0, numeric))


def _aware_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


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
            await apply_workspace_event_progress_projection(
                self._session,
                conversation_id=domain_entity.conversation_id,
                event_id=domain_entity.id,
                event_type=str(inserted_event_type),
                event_data=event_data,
                event_time_us=int(inserted_event_time_us),
                created_at=domain_entity.created_at,
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
                DBAgentExecutionEvent.id,
                DBAgentExecutionEvent.conversation_id,
                DBAgentExecutionEvent.event_type,
                DBAgentExecutionEvent.event_time_us,
                DBAgentExecutionEvent.created_at,
            )
        )
        insert_result = await self._session.execute(refresh_select_statement(self._refresh_statement(stmt)))
        projection_deltas: dict[str, dict[str, int]] = {}
        event_data_by_id = {str(item["id"]): item["event_data"] for item in values_list}
        for event_id, conversation_id, event_type, event_time_us, created_at in insert_result.all():
            delta = projection_deltas.setdefault(
                str(conversation_id),
                {"inserted_message_count": 0, "latest_event_time_us": 0},
            )
            if event_type in _MESSAGE_EVENT_TYPES:
                delta["inserted_message_count"] += 1
            delta["latest_event_time_us"] = max(delta["latest_event_time_us"], int(event_time_us))
            event_data = event_data_by_id.get(str(event_id)) or {}
            await apply_workspace_event_progress_projection(
                self._session,
                conversation_id=str(conversation_id),
                event_id=str(event_id),
                event_type=str(event_type),
                event_data=event_data if isinstance(event_data, Mapping) else {},
                event_time_us=int(event_time_us),
                created_at=created_at,
            )

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
