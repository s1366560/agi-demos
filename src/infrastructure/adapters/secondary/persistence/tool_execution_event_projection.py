"""Transactional, monotonic tool records derived from the authoritative event log."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.ports.agent.tool_executor_port import ToolExecutionStatus
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import ToolExecutionRecord


def _observation_status(data: Mapping[str, Any]) -> str:
    status = data.get("status")
    if data.get("control_outcome") and (data.get("error") or data.get("is_error")):
        return ToolExecutionStatus.FAILED.value
    if status in {
        ToolExecutionStatus.PERMISSION_DENIED.value,
        ToolExecutionStatus.CANCELLED.value,
        ToolExecutionStatus.TIMEOUT.value,
    }:
        return str(status)
    if data.get("error") or data.get("is_error") or status in {"error", "failed", "failure"}:
        return ToolExecutionStatus.FAILED.value
    if status in {None, "success", "completed"}:
        return ToolExecutionStatus.SUCCESS.value
    raise ValueError("tool observation has an unknown terminal status")


async def _pending_pause_output(
    session: AsyncSession,
    *,
    record_id: str,
    conversation_id: str,
    message_id: str,
    call_id: str,
    tool_name: str,
) -> str | None:
    """Only a producer-recorded typed pause can await a later failure."""
    table = ToolExecutionRecord
    output = (
        await session.execute(
            refresh_select_statement(
                select(table.tool_output).where(
                    table.id == record_id,
                    table.conversation_id == conversation_id,
                    table.message_id == message_id,
                    table.call_id == call_id,
                    table.tool_name == tool_name,
                    table.status == ToolExecutionStatus.CANCELLED.value,
                    table.error.is_(None),
                )
            )
        )
    ).scalar_one_or_none()
    if not isinstance(output, str):
        return None
    try:
        payload = json.loads(output)
    except ValueError:
        return None
    if (
        payload
        == {
            "type": "computer_use_control",
            "status": "user_paused",
            "retry_allowed": False,
        }
        and payload.get("retry_allowed") is False
    ):
        return output
    return None


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
    record_id, call_id, tool_name = cast(list[str], identity)
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
        controlled = status == ToolExecutionStatus.CANCELLED.value and event_data.get(
            "control_outcome"
        ) in ("user_paused", "user_stopped")
        if controlled and isinstance(result, Mapping):
            result = result.get("output", result)
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
            if status != ToolExecutionStatus.SUCCESS.value and not controlled
            else None,
            "tool_output": (
                result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            )
            if (status == ToolExecutionStatus.SUCCESS.value or controlled) and result is not None
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
    terminal_transition = table.status == ToolExecutionStatus.RUNNING.value
    if (
        event_type == "observe"
        and values["status"] == ToolExecutionStatus.FAILED.value
        and event_data.get("control_outcome") == "user_paused"
    ):
        paused_output = await _pending_pause_output(
            session,
            record_id=record_id,
            conversation_id=conversation_id,
            message_id=message_id,
            call_id=call_id,
            tool_name=tool_name,
        )
        if paused_output is not None:
            # Match the exact prior state again in the atomic update. Replayed
            # pause/success events cannot overwrite this real authority failure.
            terminal_transition = or_(
                terminal_transition,
                and_(
                    table.status == ToolExecutionStatus.CANCELLED.value,
                    table.tool_output == paused_output,
                    table.error.is_(None),
                    table.completed_at <= at,
                ),
            )
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
                terminal_transition
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
                select(
                    table.conversation_id, table.message_id, table.call_id, table.tool_name
                ).where(table.id == record_id)
            )
        )
    ).one()
    if tuple(actual) != (conversation_id, message_id, call_id, tool_name):
        raise ValueError("tool execution event identity conflicts with its durable record")
