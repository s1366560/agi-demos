"""TypedDict definitions for structured dictionary types in the agent system.

These TypedDicts replace Dict[str, Any] return types where the dictionary shape
is well-known and stable, providing better type safety and IDE support.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict, Union

# =============================================================================
# SSE / Streaming Event Dicts
# =============================================================================


class SSEEventDict(TypedDict):
    """Standard SSE event dict emitted by AgentDomainEvent.to_event_dict()."""

    type: str
    data: Dict[str, Any]
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
    input: Dict[str, Any]
    output: Optional[str]
    error: Optional[str]
    title: Optional[str]
    metadata: Dict[str, Any]
    duration_ms: Optional[int]


class TextPartDict(TypedDict):
    """Serialized TextPart from TextPart.to_dict()."""

    type: str
    text: str
    synthetic: bool


class ReasoningPartDict(TypedDict):
    """Serialized ReasoningPart from ReasoningPart.to_dict()."""

    type: str
    text: str
    metadata: Dict[str, Any]


# Union of all part dicts
MessagePartDict = Union[ToolPartDict, TextPartDict, ReasoningPartDict]


class MessageDict(TypedDict):
    """Serialized Message from Message.to_dict()."""

    id: str
    session_id: str
    role: str
    content: str
    parts: List[MessagePartDict]
    agent: Optional[str]
    parent_id: Optional[str]
    finish_reason: Optional[str]
    tokens: Dict[str, int]
    cost: float
    error: Optional[Dict[str, Any]]
    created_at: float
    completed_at: Optional[float]


class LLMMessageDict(TypedDict, total=False):
    """Serialized Message from Message.to_llm_format().

    Uses total=False because tool_calls is only present on assistant messages
    that have tool parts.
    """

    role: str
    content: Optional[str]
    tool_calls: List[Dict[str, Any]]


# =============================================================================
# Todo Pending Event Dicts (from todo_tools.py)
# =============================================================================


class TaskListUpdatedEventData(TypedDict):
    """Pending event emitted on replace/add actions."""

    type: str
    conversation_id: str
    tasks: List[Dict[str, Any]]


class TaskUpdatedEventData(TypedDict):
    """Pending event emitted on update action."""

    type: str
    conversation_id: str
    task_id: str
    status: str
    content: Optional[str]


TodoPendingEvent = Union[TaskListUpdatedEventData, TaskUpdatedEventData]
