"""Join streamed tool drafts using protocol identities within their message."""

from typing import Any, Protocol

EventIdentity = tuple[int, int, str]


class ToolHistoryEvent(Protocol):
    event_type: str
    event_data: dict[str, Any] | None
    message_id: str | None
    event_time_us: int
    event_counter: int


def event_identity(event: ToolHistoryEvent) -> EventIdentity:
    return (event.event_time_us, event.event_counter, event.event_type)


def _call_identity(event: ToolHistoryEvent) -> tuple[str, str, str]:
    data = event.event_data or {}
    message_id = str(event.message_id or data.get("message_id") or "")
    call_id = str(data.get("call_id") or "")
    execution_id = str(data.get("tool_execution_id") or data.get("execution_id") or "")
    # Older drafts stored the model call id in execution_id before an execution
    # record existed. That value is a call alias, not an independent execution.
    if event.event_type == "act_delta" and execution_id == call_id:
        execution_id = ""
    return message_id, call_id, execution_id


def replayable_act_delta_ids(events: list[ToolHistoryEvent]) -> set[EventIdentity]:
    """Keep the latest unmatched draft without suppressing independent executions."""
    latest_drafts: dict[tuple[str, str, str] | EventIdentity, ToolHistoryEvent] = {}
    full_calls: set[tuple[str, str]] = set()
    full_executions: set[tuple[str, str]] = set()
    for event in events:
        if event.event_type not in {"act", "act_delta"}:
            continue
        message_id, call_id, execution_id = _call_identity(event)
        if event.event_type == "act":
            if call_id:
                full_calls.add((message_id, call_id))
            if execution_id:
                full_executions.add((message_id, execution_id))
            continue
        key = (
            (message_id, call_id, execution_id)
            if call_id or execution_id
            else event_identity(event)
        )
        latest_drafts[key] = event

    replayable: set[EventIdentity] = set()
    for event in latest_drafts.values():
        message_id, call_id, execution_id = _call_identity(event)
        matched = (
            (message_id, execution_id) in full_executions
            if execution_id
            else bool(call_id) and (message_id, call_id) in full_calls
        )
        if not matched:
            replayable.add(event_identity(event))
    return replayable
