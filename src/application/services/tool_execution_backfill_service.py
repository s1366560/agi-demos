"""Backfill tool_execution_records from historical agent_execution_events."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent as DBAgentExecutionEvent,
    ToolExecutionRecord as DBToolExecutionRecord,
)

logger = logging.getLogger(__name__)

_TOOL_EVENT_TYPES = ("act", "observe")
_TERMINAL_STATUSES = {
    ToolExecutionStatus.SUCCESS.value,
    ToolExecutionStatus.FAILED.value,
    ToolExecutionStatus.CANCELLED.value,
    ToolExecutionStatus.TIMEOUT.value,
    ToolExecutionStatus.PERMISSION_DENIED.value,
}


@dataclass(slots=True)
class ToolExecutionBackfillStats:
    """Summary of a historical tool execution backfill run."""

    events_scanned: int = 0
    events_skipped: int = 0
    records_seen: int = 0
    records_inserted: int = 0
    records_updated: int = 0
    records_unchanged: int = 0


@dataclass(slots=True)
class _ToolRecordDraft:
    id: str
    conversation_id: str
    message_id: str
    call_id: str
    tool_name: str
    tool_input: dict[str, Any] = field(default_factory=dict)
    tool_output: str | None = None
    status: str = ToolExecutionStatus.RUNNING.value
    error: str | None = None
    sequence_number: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    duration_ms: int | None = None


class ToolExecutionBackfillService:
    """Create missing tool execution records from the durable event timeline."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def backfill(
        self,
        *,
        conversation_id: str | None = None,
        limit: int | None = None,
        apply_changes: bool = False,
    ) -> ToolExecutionBackfillStats:
        """Backfill historical act/observe events into tool_execution_records."""
        stats = ToolExecutionBackfillStats()
        drafts = await self._load_drafts(conversation_id=conversation_id, limit=limit, stats=stats)
        stats.records_seen = len(drafts)

        for draft in drafts.values():
            existing = await self._find_existing(draft.id)
            if existing is None:
                if apply_changes:
                    self._session.add(self._to_db(draft))
                stats.records_inserted += 1
                continue

            if not apply_changes:
                changed = self._existing_needs_merge(existing, draft)
                if changed:
                    stats.records_updated += 1
                else:
                    stats.records_unchanged += 1
                continue

            changed = self._merge_existing(existing, draft)
            if changed:
                stats.records_updated += 1
            else:
                stats.records_unchanged += 1

        if apply_changes:
            await self._session.flush()
        return stats

    async def _load_drafts(
        self,
        *,
        conversation_id: str | None,
        limit: int | None,
        stats: ToolExecutionBackfillStats,
    ) -> dict[str, _ToolRecordDraft]:
        stmt = select(DBAgentExecutionEvent).where(
            DBAgentExecutionEvent.event_type.in_(_TOOL_EVENT_TYPES)
        )
        if conversation_id:
            stmt = stmt.where(DBAgentExecutionEvent.conversation_id == conversation_id)
        stmt = stmt.order_by(
            DBAgentExecutionEvent.conversation_id.asc(),
            DBAgentExecutionEvent.event_time_us.asc(),
            DBAgentExecutionEvent.event_counter.asc(),
        )
        if limit:
            stmt = stmt.limit(limit)

        rows = (await self._session.execute(refresh_select_statement(stmt))).scalars().all()
        drafts: dict[str, _ToolRecordDraft] = {}
        for row in rows:
            stats.events_scanned += 1
            payload = _event_payload(row.event_data)
            identity = _record_identity(row, payload)
            if identity is None:
                stats.events_skipped += 1
                continue

            record_id, message_id, call_id, tool_name = identity
            draft = drafts.get(record_id)
            if draft is None:
                draft = _ToolRecordDraft(
                    id=record_id,
                    conversation_id=row.conversation_id,
                    message_id=message_id,
                    call_id=call_id,
                    tool_name=tool_name,
                    sequence_number=row.event_counter,
                    started_at=_timestamp_from_event_time(row.event_time_us),
                )
                drafts[record_id] = draft

            _apply_event_to_draft(draft, row, payload)
        return drafts

    async def _find_existing(self, record_id: str) -> DBToolExecutionRecord | None:
        result = await self._session.execute(
            refresh_select_statement(
                select(DBToolExecutionRecord).where(DBToolExecutionRecord.id == record_id)
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    def _to_db(draft: _ToolRecordDraft) -> DBToolExecutionRecord:
        return DBToolExecutionRecord(
            id=draft.id,
            conversation_id=draft.conversation_id,
            message_id=draft.message_id,
            call_id=draft.call_id,
            tool_name=draft.tool_name,
            tool_input=draft.tool_input,
            tool_output=draft.tool_output,
            status=draft.status,
            error=draft.error,
            step_number=None,
            sequence_number=draft.sequence_number,
            started_at=draft.started_at,
            completed_at=draft.completed_at,
            duration_ms=draft.duration_ms,
        )

    @staticmethod
    def _merge_existing(existing: DBToolExecutionRecord, draft: _ToolRecordDraft) -> bool:
        changed = False

        if not existing.tool_input and draft.tool_input:
            existing.tool_input = draft.tool_input
            changed = True
        if draft.started_at and draft.started_at < existing.started_at:
            existing.started_at = draft.started_at
            changed = True
        if draft.completed_at and (
            existing.completed_at is None or draft.completed_at > existing.completed_at
        ):
            existing.completed_at = draft.completed_at
            changed = True
        if draft.duration_ms is not None and existing.duration_ms is None:
            existing.duration_ms = draft.duration_ms
            changed = True
        if draft.tool_output is not None and not existing.tool_output:
            existing.tool_output = draft.tool_output
            changed = True
        if draft.error is not None and not existing.error:
            existing.error = draft.error
            changed = True
        if existing.status not in _TERMINAL_STATUSES or draft.status in _TERMINAL_STATUSES:
            if existing.status != draft.status:
                existing.status = draft.status
                changed = True
        return changed

    @staticmethod
    def _existing_needs_merge(existing: DBToolExecutionRecord, draft: _ToolRecordDraft) -> bool:
        return any(
            (
                bool(not existing.tool_input and draft.tool_input),
                bool(
                    draft.started_at
                    and draft.started_at < existing.started_at
                ),
                bool(
                    draft.completed_at
                    and (
                        existing.completed_at is None
                        or draft.completed_at > existing.completed_at
                    )
                ),
                draft.duration_ms is not None and existing.duration_ms is None,
                draft.tool_output is not None and not existing.tool_output,
                draft.error is not None and not existing.error,
                (
                    (
                        existing.status not in _TERMINAL_STATUSES
                        or draft.status in _TERMINAL_STATUSES
                    )
                    and existing.status != draft.status
                ),
            )
        )


def _event_payload(event_data: object) -> Mapping[str, Any]:
    """Normalize legacy event payload shapes."""
    if not isinstance(event_data, Mapping):
        return {}
    nested = event_data.get("data")
    if isinstance(nested, Mapping) and not any(
        key in event_data for key in ("tool_execution_id", "call_id", "tool_name")
    ):
        return nested
    return event_data


def _record_identity(
    row: DBAgentExecutionEvent,
    payload: Mapping[str, Any],
) -> tuple[str, str, str, str] | None:
    call_id = _first_str(payload.get("call_id"), payload.get("tool_call_id"))
    tool_name = _first_str(payload.get("tool_name"), payload.get("tool"))
    if not call_id or not tool_name:
        logger.debug(
            "Skipping legacy tool event without call/tool identity: event_id=%s type=%s",
            row.id,
            row.event_type,
        )
        return None

    message_id = _first_str(
        row.message_id,
        payload.get("message_id"),
        payload.get("response_id"),
        row.correlation_id,
    )
    if not message_id:
        message_id = f"legacy:{row.conversation_id}"

    record_id = _first_str(payload.get("tool_execution_id"))
    if not record_id:
        raw = f"{row.conversation_id}|{message_id}|{call_id}|{tool_name}"
        record_id = f"legacy-tool:{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:32]}"

    return record_id, message_id, call_id, tool_name


def _apply_event_to_draft(
    draft: _ToolRecordDraft,
    row: DBAgentExecutionEvent,
    payload: Mapping[str, Any],
) -> None:
    event_at = _timestamp_from_event_time(row.event_time_us)
    draft.sequence_number = min(draft.sequence_number, row.event_counter)
    if row.event_type == "act":
        draft.tool_input = _coerce_tool_input(payload.get("tool_input"))
        if draft.started_at is None or event_at < draft.started_at:
            draft.started_at = event_at
        if draft.status not in _TERMINAL_STATUSES:
            draft.status = ToolExecutionStatus.RUNNING.value
        return

    draft.completed_at = event_at
    draft.duration_ms = _coerce_duration_ms(payload.get("duration_ms"))
    if _is_failed_tool_observation(payload):
        draft.status = ToolExecutionStatus.FAILED.value
        draft.error = _sanitize_text(str(payload.get("error") or "Tool execution failed"))
        return

    draft.status = ToolExecutionStatus.SUCCESS.value
    draft.tool_output = _serialize_tool_result(payload.get("result"))
    draft.error = None


def _first_str(*values: object) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return _sanitize_text(value.strip())
    return None


def _timestamp_from_event_time(event_time_us: int) -> datetime:
    if event_time_us <= 0:
        return datetime.now(UTC)
    return datetime.fromtimestamp(event_time_us / 1_000_000, UTC)


def _coerce_tool_input(tool_input: object) -> dict[str, Any]:
    if isinstance(tool_input, Mapping):
        return _sanitize_json_mapping(tool_input)
    if tool_input is None:
        return {}
    return {"value": _sanitize_jsonable(tool_input)}


def _coerce_duration_ms(duration_ms: object) -> int | None:
    if duration_ms is None:
        return None
    if not isinstance(duration_ms, int | float | str):
        return None
    try:
        return int(duration_ms)
    except (TypeError, ValueError):
        return None


def _serialize_tool_result(result: object) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return _sanitize_text(result)
    try:
        return json.dumps(_sanitize_jsonable(result), ensure_ascii=False, default=str)
    except TypeError:
        return _sanitize_text(str(result))


def _is_failed_tool_observation(event_data: Mapping[str, Any]) -> bool:
    status = str(event_data.get("status") or "").lower()
    return bool(event_data.get("error")) or status in {"error", "failed", "failure"}


def _sanitize_text(value: str) -> str:
    return value.replace("\x00", "")


def _sanitize_json_mapping(value: Mapping[str, Any]) -> dict[str, Any]:
    return {str(key): _sanitize_jsonable(item) for key, item in value.items()}


def _sanitize_jsonable(value: object) -> object:
    if isinstance(value, str):
        return _sanitize_text(value)
    if isinstance(value, Mapping):
        return _sanitize_json_mapping(value)
    if isinstance(value, list):
        return [_sanitize_jsonable(item) for item in value]
    return value
