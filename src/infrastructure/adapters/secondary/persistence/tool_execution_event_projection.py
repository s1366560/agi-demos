"""Transactional, monotonic tool records derived from the authoritative event log."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import ToolExecutionRecord


def _observation_status(data: Mapping[str, Any]) -> str:
    status = data.get("status")
    if status in {
        ToolExecutionStatus.PERMISSION_DENIED.value,
        ToolExecutionStatus.CANCELLED.value,
        ToolExecutionStatus.TIMEOUT.value,
    }:
        return str(status)
    if data.get("error") or status in {"error", "failed", "failure"}:
        return ToolExecutionStatus.FAILED.value
    if status in {None, "success", "completed"}:
        return ToolExecutionStatus.SUCCESS.value
    raise ValueError("tool observation has an unknown terminal status")


async def apply_tool_execution_event_projection(
    session: AsyncSession,
    *,
    conversation_id: str,
    message_id: str,
    event_type: str,
    event_data: Mapping[str, Any],
    event_time_us: int,
    event_counter: int,
) -> None:
    """Use already sanitized event data; never commit outside the caller's transaction."""
    if event_type not in {"act", "observe"}:
        return
    identity = [event_data.get(key) for key in ("tool_execution_id", "call_id", "tool_name")]
    # Legacy events without execution identity remain in the log, without invented records.
    if not all(isinstance(value, str) and value for value in identity):
        return
    record_id, call_id, tool_name = identity
    at = datetime.fromtimestamp(event_time_us / 1_000_000, UTC)
    tool_input = event_data.get("tool_input")
    values: dict[str, Any] = {
        "id": record_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "call_id": call_id,
        "tool_name": tool_name,
        "tool_input": dict(tool_input) if isinstance(tool_input, Mapping) else {},
        "status": ToolExecutionStatus.RUNNING.value,
        "sequence_number": event_counter,
        "started_at": at,
    }
    update_values: dict[str, Any]
    if event_type == "observe":
        status = _observation_status(event_data)
        result = event_data.get("result")
        try:
            duration = (
                int(event_data["duration_ms"])
                if event_data.get("duration_ms") is not None
                else None
            )
        except (ValueError, TypeError):
            duration = None
        update_values = {
            "status": status,
            "completed_at": at,
            "duration_ms": duration,
            "error": str(event_data.get("error") or "Tool execution failed")
            if status != ToolExecutionStatus.SUCCESS.value
            else None,
            "tool_output": (
                result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            )
            if status == ToolExecutionStatus.SUCCESS.value and result is not None
            else None,
        }
        values.update(update_values)
    else:
        update_values = {
            "tool_input": values["tool_input"],
            "sequence_number": event_counter,
            "started_at": at,
        }
    table = ToolExecutionRecord
    await session.execute(
        insert(table)
        .values(**values)
        .on_conflict_do_update(
            index_elements=[table.id],
            set_=update_values,
            where=and_(
                table.conversation_id == conversation_id,
                table.message_id == message_id,
                table.call_id == call_id,
                table.tool_name == tool_name,
                table.status == ToolExecutionStatus.RUNNING.value
                if event_type == "observe"
                else or_(
                    table.started_at > at,
                    and_(table.started_at == at, table.sequence_number > event_counter),
                ),
            ),
        )
    )
    # A colliding id must not reassign another scope/call, even if it is terminal.
    actual = (
        await session.execute(
            refresh_select_statement(
                select(table.conversation_id, table.message_id, table.call_id, table.tool_name).where(
                    table.id == record_id
                )
            )
        )
    ).one()
    if tuple(actual) != (conversation_id, message_id, call_id, tool_name):
        raise ValueError("tool execution event identity conflicts with its durable record")
