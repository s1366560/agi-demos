"""TypedDict definitions for structured dictionary types in the agent system.

These TypedDicts replace Dict[str, Any] return types where the dictionary shape
is well-known and stable, providing better type safety and IDE support.
"""

from __future__ import annotations

from typing import Any, TypedDict

# =============================================================================
# SSE / Streaming Event Dicts
# =============================================================================


class SSEEventDict(TypedDict):
    """Standard SSE event dict emitted by AgentDomainEvent.to_event_dict()."""

    type: str
    data: dict[str, Any]
    timestamp: str


# =============================================================================
# Message Part Dicts (from message.py to_dict() methods)
# =============================================================================


class ToolPartDict(TypedDict):
    """Serialized ToolPart from ToolPart.to_dict()."""

    type: str
    call_id: str
    tool: str
    status: str
    input: dict[str, Any]
    output: str | None
    error: str | None
    title: str | None
    metadata: dict[str, Any]
    duration_ms: int | None


class TextPartDict(TypedDict):
    """Serialized TextPart from TextPart.to_dict()."""

    type: str
    text: str
    synthetic: bool


class ReasoningPartDict(TypedDict):
    """Serialized ReasoningPart from ReasoningPart.to_dict()."""

    type: str
    text: str
    metadata: dict[str, Any]


# Union of all part dicts
MessagePartDict = ToolPartDict | TextPartDict | ReasoningPartDict


class MessageDict(TypedDict):
    """Serialized Message from Message.to_dict()."""

    id: str
    session_id: str
    role: str
    content: str
    parts: list[MessagePartDict]
    agent: str | None
    parent_id: str | None
    finish_reason: str | None
    tokens: dict[str, int]
    cost: float
    error: dict[str, Any] | None
    created_at: float
    completed_at: float | None


class LLMMessageDict(TypedDict, total=False):
    """Serialized Message from Message.to_llm_format().

    Uses total=False because tool_calls is only present on assistant messages
    that have tool parts.
    """

    role: str
    content: str | None
    tool_calls: list[dict[str, Any]]


# =============================================================================
# Todo Pending Event Dicts (from todo_tools.py)
# =============================================================================


class TaskListUpdatedEventData(TypedDict):
    """Pending event emitted on replace/add actions."""

    type: str
    conversation_id: str
    tasks: list[dict[str, Any]]


class TaskUpdatedEventData(TypedDict):
    """Pending event emitted on update action."""

    type: str
    conversation_id: str
    task_id: str
    status: str
    content: str | None


TodoPendingEvent = TaskListUpdatedEventData | TaskUpdatedEventData
