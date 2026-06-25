"""Map MemStack agent stream events to ACP session updates."""
# ruff: noqa: ANN401

from __future__ import annotations

import uuid
from typing import Any, Literal

from acp.schema import (
    AgentMessageChunk,
    AgentPlanUpdate,
    AgentThoughtChunk,
    PlanEntry,
    SessionInfoUpdate,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
    UsageUpdate,
    UserMessageChunk,
)
from pydantic import BaseModel

ACPUpdate = (
    AgentMessageChunk
    | AgentThoughtChunk
    | AgentPlanUpdate
    | ToolCallStart
    | ToolCallProgress
    | UsageUpdate
    | UserMessageChunk
    | SessionInfoUpdate
)

_PlanStatus = Literal["pending", "in_progress", "completed"]
_PlanPriority = Literal["high", "medium", "low"]
_ToolStatus = Literal["pending", "in_progress", "completed", "failed"]
_ToolKind = Literal[
    "read",
    "edit",
    "delete",
    "move",
    "search",
    "execute",
    "think",
    "fetch",
    "switch_mode",
    "other",
]


def memstack_event_to_acp_updates(event: dict[str, Any]) -> list[ACPUpdate]:  # noqa: C901, PLR0911
    """Convert one MemStack stream event to zero or more ACP update models."""
    event_type = str(event.get("type") or "unknown")
    data = _as_dict(event.get("data"))
    meta = _meta_for(event_type, event, data)

    if event_type == "message":
        content = _text_from_data(data)
        if not content:
            return [_session_info(event, meta)]
        message_id = _message_id(data, event)
        block = _text_block(content)
        if data.get("role") == "user":
            return [
                UserMessageChunk(
                    session_update="user_message_chunk",
                    content=block,
                    message_id=message_id,
                    field_meta=meta,
                )
            ]
        return [
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=block,
                message_id=message_id,
                field_meta=meta,
            )
        ]

    if event_type in {"text_delta", "message_delta", "assistant_delta"}:
        content = _text_from_data(data)
        if content:
            return [
                AgentMessageChunk(
                    session_update="agent_message_chunk",
                    content=_text_block(content),
                    message_id=_message_id(data, event),
                    field_meta=meta,
                )
            ]

    if event_type in {"thought", "thought_delta"}:
        content = _text_from_data(data)
        if content:
            return [
                AgentThoughtChunk(
                    session_update="agent_thought_chunk",
                    content=_text_block(content),
                    message_id=_message_id(data, event),
                    field_meta=meta,
                )
            ]

    if event_type == "error":
        content = _error_text(data)
        return [
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=_text_block(content),
                message_id=_message_id(data, event),
                field_meta=meta,
            )
        ]

    if event_type in {"task_list_updated", "task_updated", "work_plan", "plan_update"}:
        entries = _plan_entries(data)
        if entries:
            return [AgentPlanUpdate(session_update="plan", entries=entries, field_meta=meta)]

    if _is_tool_event(event_type, data):
        return [_tool_update(event_type, event, data, meta)]

    usage = _usage_update(data, meta)
    if usage is not None:
        return [usage]

    return [_session_info(event, meta)]


def update_to_payload(update: BaseModel) -> dict[str, Any]:
    """Dump an ACP update with protocol aliases."""
    return update.model_dump(mode="json", by_alias=True, exclude_none=True, exclude_unset=True)


def _text_block(text: str) -> TextContentBlock:
    return TextContentBlock(type="text", text=text)


def _text_from_data(data: dict[str, Any]) -> str | None:
    for key in ("content", "text", "delta", "message", "summary"):
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _error_text(data: dict[str, Any]) -> str:
    content = _text_from_data(data)
    if content:
        return content
    error = data.get("error")
    if isinstance(error, str) and error:
        return error
    return "MemStack agent execution failed"


def _message_id(data: dict[str, Any], event: dict[str, Any]) -> str | None:
    for value in (data.get("message_id"), data.get("messageId"), event.get("message_id"), event.get("id")):
        if isinstance(value, str) and value:
            return value
    return None


def _meta_for(event_type: str, event: dict[str, Any], data: dict[str, Any]) -> dict[str, Any]:
    memstack: dict[str, Any] = {"eventType": event_type}
    for source_key, target_key in (
        ("correlation_id", "correlationId"),
        ("event_time_us", "eventTimeUs"),
        ("event_counter", "eventCounter"),
        ("timestamp", "timestamp"),
    ):
        if source_key in event:
            memstack[target_key] = event[source_key]
    if "conversation_id" in data:
        memstack["conversationId"] = data["conversation_id"]
    return {"memstack": memstack}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _plan_entries(data: dict[str, Any]) -> list[PlanEntry]:
    raw_items = (
        data.get("tasks")
        or data.get("items")
        or data.get("entries")
        or data.get("task_list")
        or data.get("plan")
    )
    if isinstance(raw_items, dict):
        raw_items = raw_items.get("tasks") or raw_items.get("items") or raw_items.get("entries")
    if not isinstance(raw_items, list):
        return []

    entries: list[PlanEntry] = []
    for item in raw_items:
        if isinstance(item, str):
            content = item
            status: _PlanStatus = "pending"
            priority: _PlanPriority = "medium"
        elif isinstance(item, dict):
            content_candidate = _first_str(
                item,
                "content",
                "title",
                "description",
                "task",
                "step",
            )
            if not content_candidate:
                continue
            content = content_candidate
            status = _plan_status(item.get("status"))
            priority = _plan_priority(item.get("priority"))
        else:
            continue
        entries.append(PlanEntry(content=content, status=status, priority=priority))
    return entries


def _plan_status(value: Any) -> _PlanStatus:
    normalized = str(value or "").lower()
    if normalized in {"in_progress", "in-progress", "running", "started", "active"}:
        return "in_progress"
    if normalized in {"completed", "complete", "done", "success", "succeeded"}:
        return "completed"
    return "pending"


def _plan_priority(value: Any) -> _PlanPriority:
    normalized = str(value or "").lower()
    if normalized == "high":
        return "high"
    if normalized == "low":
        return "low"
    return "medium"


def _is_tool_event(event_type: str, data: dict[str, Any]) -> bool:
    if event_type in {
        "act",
        "observe",
        "tool_call",
        "tool_call_update",
        "tool_started",
        "tool_completed",
        "tool_error",
    }:
        return True
    return any(key in data for key in ("tool_call_id", "toolCallId", "tool_name", "tool"))


def _tool_update(
    event_type: str,
    event: dict[str, Any],
    data: dict[str, Any],
    meta: dict[str, Any],
) -> ToolCallStart | ToolCallProgress:
    tool_call_id = _tool_call_id(event, data)
    title = _tool_title(event_type, data)
    kind = _tool_kind(data)
    status = _tool_status(event_type, data)
    raw_input = data.get("input") or data.get("arguments") or data.get("args")
    raw_output = data.get("output") or data.get("result") or data.get("observation")

    if event_type in {"act", "tool_call", "tool_started"}:
        return ToolCallStart(
            session_update="tool_call",
            tool_call_id=tool_call_id,
            title=title,
            kind=kind,
            status=status,
            raw_input=raw_input,
            raw_output=raw_output,
            field_meta=meta,
        )
    return ToolCallProgress(
        session_update="tool_call_update",
        tool_call_id=tool_call_id,
        title=title,
        kind=kind,
        status=status,
        raw_input=raw_input,
        raw_output=raw_output,
        field_meta=meta,
    )


def _tool_call_id(event: dict[str, Any], data: dict[str, Any]) -> str:
    for value in (data.get("tool_call_id"), data.get("toolCallId"), data.get("id"), event.get("id")):
        if isinstance(value, str) and value:
            return value
    return str(uuid.uuid4())


def _tool_title(event_type: str, data: dict[str, Any]) -> str:
    explicit = _first_str(data, "title", "name", "tool_name", "tool")
    if explicit:
        return explicit
    return event_type.replace("_", " ").title()


def _tool_status(event_type: str, data: dict[str, Any]) -> _ToolStatus:
    normalized = str(data.get("status") or "").lower()
    if normalized in {"failed", "error", "errored"} or event_type == "tool_error":
        return "failed"
    if normalized in {"completed", "complete", "done", "success", "succeeded"}:
        return "completed"
    if event_type in {"observe", "tool_completed"}:
        return "completed"
    if normalized == "pending":
        return "pending"
    return "in_progress"


def _tool_kind(data: dict[str, Any]) -> _ToolKind:  # noqa: PLR0911
    raw = str(data.get("kind") or data.get("tool_name") or data.get("tool") or "").lower()
    tokens = _tool_name_tokens(raw)
    if _has_any_token(tokens, "read", "list", "glob", "grep", "cat"):
        return "read"
    if _has_any_token(tokens, "write", "edit", "patch", "replace", "format"):
        return "edit"
    if _has_any_token(tokens, "delete", "remove", "rm"):
        return "delete"
    if _has_any_token(tokens, "move", "rename", "mv"):
        return "move"
    if _has_any_token(tokens, "search", "find", "query"):
        return "search"
    if _has_any_token(tokens, "fetch", "http", "web", "open"):
        return "fetch"
    if _has_any_token(tokens, "think", "reason"):
        return "think"
    if _has_any_token(tokens, "terminal", "shell", "exec", "run", "command"):
        return "execute"
    return "other"


def _tool_name_tokens(raw: str) -> set[str]:
    normalized = raw
    for separator in (".", "_", "-", "/", ":"):
        normalized = normalized.replace(separator, " ")
    return {token for token in normalized.split() if token}


def _has_any_token(tokens: set[str], *candidates: str) -> bool:
    return bool(tokens.intersection(candidates))


def _usage_update(data: dict[str, Any], meta: dict[str, Any]) -> UsageUpdate | None:
    used = _int_value(data, "used", "used_tokens", "tokens_used", "context_used")
    size = _int_value(data, "size", "total", "total_tokens", "context_size", "limit")
    if used is None or size is None:
        return None
    return UsageUpdate(session_update="usage_update", used=used, size=size, field_meta=meta)


def _session_info(event: dict[str, Any], meta: dict[str, Any]) -> SessionInfoUpdate:
    title = None
    data = _as_dict(event.get("data"))
    if isinstance(data.get("title"), str):
        title = data["title"]
    updated_at = event.get("timestamp")
    return SessionInfoUpdate(
        session_update="session_info_update",
        title=title,
        updated_at=updated_at if isinstance(updated_at, str) else None,
        field_meta=meta,
    )


def _first_str(data: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _int_value(data: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, int) and value >= 0:
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None
