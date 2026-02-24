"""Event definitions for memstack-agent.

This module defines the event types emitted during agent execution.
All events are immutable (frozen dataclass) and include timestamps.
"""

import time
from dataclasses import dataclass, field
from typing import Any

from memstack_agent.core.types import EventType, get_event_category


@dataclass(frozen=True, kw_only=True)
class AgentEvent:
    """Base class for all agent events.

    All events are immutable and include:
    - event_type: The type of event (from EventType enum)
    - timestamp: Unix timestamp when event was created
    - metadata: Optional additional data

    Subclasses add type-specific fields.
    """

    event_type: EventType
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary representation.

        This format is suitable for:
        - SSE (Server-Sent Events) transmission
        - WebSocket messaging
        - JSON serialization

        Returns:
            Dictionary with type, data, and timestamp fields
        """
        from datetime import datetime

        # Get all fields except event_type and timestamp
        data_fields = {
            k: v for k, v in self.__dict__.items() if k not in ("event_type", "timestamp")
        }

        return {
            "type": self.event_type.value,
            "data": data_fields,
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
            "category": get_event_category(self.event_type).value,
        }


# ============================================================================
# Status Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class StatusEvent(AgentEvent):
    """Generic status update event."""

    event_type: EventType = EventType.STATUS
    status: str
    message: str | None = None


@dataclass(frozen=True, kw_only=True)
class StartEvent(AgentEvent):
    """Event emitted when agent starts processing."""

    event_type: EventType = EventType.START
    conversation_id: str
    user_id: str
    model: str


@dataclass(frozen=True, kw_only=True)
class CompleteEvent(AgentEvent):
    """Event emitted when agent completes successfully.

    May include final result or trace URL for observability.
    """

    event_type: EventType = EventType.COMPLETE
    conversation_id: str
    result: Any | None = None
    trace_url: str | None = None
    tokens: dict[str, int] = field(default_factory=dict)
    cost: float = 0.0


@dataclass(frozen=True, kw_only=True)
class ErrorEvent(AgentEvent):
    """Event emitted when an error occurs.

    Includes error message and optional error code/details.
    """

    event_type: EventType = EventType.ERROR
    conversation_id: str
    message: str
    code: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Thinking Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ThoughtEvent(AgentEvent):
    """Event representing agent's thought/reasoning.

    Emitted during the THINK phase of ReAct loop.
    """

    event_type: EventType = EventType.THOUGHT
    conversation_id: str
    content: str
    step_index: int | None = None
    thought_level: str = "task"  # task, subtask, plan


@dataclass(frozen=True, kw_only=True)
class ThoughtDeltaEvent(AgentEvent):
    """Streaming fragment of thought content.

    Emitted progressively as LLM streams reasoning tokens.
    """

    event_type: EventType = EventType.THOUGHT_DELTA
    conversation_id: str
    delta: str
    step_index: int | None = None


# ============================================================================
# Tool Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ActEvent(AgentEvent):
    """Event: Agent calls a tool.

    The tool_execution_id uniquely identifies this tool execution
    and is used to match with the corresponding ObserveEvent.
    """

    event_type: EventType = EventType.ACT
    conversation_id: str
    tool_name: str
    tool_input: dict[str, Any]
    call_id: str | None = None
    status: str = "running"
    tool_execution_id: str | None = None


@dataclass(frozen=True, kw_only=True)
class ActDeltaEvent(AgentEvent):
    """Event: Streaming tool call argument fragments.

    Emitted progressively as tool call arguments are received
    from the LLM, allowing UI to show preparation state.
    """

    event_type: EventType = EventType.ACT_DELTA
    conversation_id: str
    tool_name: str
    call_id: str | None = None
    arguments_fragment: str = ""
    accumulated_arguments: str = ""
    status: str = "preparing"


@dataclass(frozen=True, kw_only=True)
class ObserveEvent(AgentEvent):
    """Event: Tool execution result.

    The tool_execution_id must match the corresponding ActEvent
    for reliable act/observe pairing in the UI.
    """

    event_type: EventType = EventType.OBSERVE
    conversation_id: str
    tool_name: str
    result: Any | None = None
    error: str | None = None
    duration_ms: int | None = None
    call_id: str | None = None
    status: str = "completed"
    tool_execution_id: str | None = None


# ============================================================================
# Text Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class TextStartEvent(AgentEvent):
    """Event: Agent starts generating text response."""

    event_type: EventType = EventType.TEXT_START
    conversation_id: str


@dataclass(frozen=True, kw_only=True)
class TextDeltaEvent(AgentEvent):
    """Event: Streaming text fragment.

    Emitted as LLM streams response tokens for the final answer.
    """

    event_type: EventType = EventType.TEXT_DELTA
    conversation_id: str
    delta: str


@dataclass(frozen=True, kw_only=True)
class TextEndEvent(AgentEvent):
    """Event: Agent finishes generating text response.

    Includes the complete text for clients that didn't accumulate deltas.
    """

    event_type: EventType = EventType.TEXT_END
    conversation_id: str
    full_text: str | None = None


# ============================================================================
# Message Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class MessageEvent(AgentEvent):
    """Event: Complete message (user or assistant).

    Used for full message synchronization rather than streaming.
    """

    event_type: EventType = EventType.MESSAGE
    conversation_id: str
    role: str  # user, assistant, system
    content: str
    message_id: str | None = None
    attachment_ids: list[str] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


# ============================================================================
# Permission Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class PermissionAskedEvent(AgentEvent):
    """Event: Agent requests user permission for an action."""

    event_type: EventType = EventType.PERMISSION_ASKED
    conversation_id: str
    request_id: str
    permission: str
    patterns: list[str]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class PermissionRepliedEvent(AgentEvent):
    """Event: User responds to permission request."""

    event_type: EventType = EventType.PERMISSION_REPLIED
    conversation_id: str
    request_id: str
    granted: bool


# ============================================================================
# Doom Loop Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class DoomLoopDetectedEvent(AgentEvent):
    """Event: Doom loop (repeated tool calls) detected."""

    event_type: EventType = EventType.DOOM_LOOP_DETECTED
    conversation_id: str
    tool: str
    input: dict[str, Any]
    occurrences: int


@dataclass(frozen=True, kw_only=True)
class DoomLoopIntervenedEvent(AgentEvent):
    """Event: System intervened to stop doom loop."""

    event_type: EventType = EventType.DOOM_LOOP_INTERVENED
    conversation_id: str
    request_id: str
    action: str  # stop, warn, redirect


# ============================================================================
# HITL Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class ClarificationAskedEvent(AgentEvent):
    """Event: Agent requests user clarification."""

    event_type: EventType = EventType.CLARIFICATION_ASKED
    conversation_id: str
    request_id: str
    question: str
    clarification_type: str
    options: list[dict[str, Any]]
    allow_custom: bool = True
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class ClarificationAnsweredEvent(AgentEvent):
    """Event: User responds to clarification request."""

    event_type: EventType = EventType.CLARIFICATION_ANSWERED
    conversation_id: str
    request_id: str
    answer: str


@dataclass(frozen=True, kw_only=True)
class DecisionAskedEvent(AgentEvent):
    """Event: Agent requests user decision between options."""

    event_type: EventType = EventType.DECISION_ASKED
    conversation_id: str
    request_id: str
    question: str
    decision_type: str
    options: list[dict[str, Any]]
    allow_custom: bool = False
    default_option: str | None = None
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True)
class DecisionAnsweredEvent(AgentEvent):
    """Event: User responds to decision request."""

    event_type: EventType = EventType.DECISION_ANSWERED
    conversation_id: str
    request_id: str
    decision: str


# ============================================================================
# Cost and Retry Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class CostUpdateEvent(AgentEvent):
    """Event: Cost/tokens updated during processing."""

    event_type: EventType = EventType.COST_UPDATE
    conversation_id: str
    cost: float
    tokens: dict[str, int]


@dataclass(frozen=True, kw_only=True)
class RetryEvent(AgentEvent):
    """Event: Operation being retried with backoff."""

    event_type: EventType = EventType.RETRY
    conversation_id: str
    attempt: int
    delay_ms: int
    message: str


# ============================================================================
# Context Events
# ============================================================================


@dataclass(frozen=True, kw_only=True)
class CompactNeededEvent(AgentEvent):
    """Event: Context compaction needed to fit token limits."""

    event_type: EventType = EventType.COMPACT_NEEDED
    conversation_id: str
    compression_level: str = ""
    current_tokens: int = 0
    token_budget: int = 0
    occupancy_pct: float = 0.0


@dataclass(frozen=True, kw_only=True)
class ContextCompressedEvent(AgentEvent):
    """Event: Context was compressed to save tokens."""

    event_type: EventType = EventType.CONTEXT_COMPRESSED
    conversation_id: str
    was_compressed: bool
    compression_strategy: str
    compression_level: str = ""
    original_message_count: int
    final_message_count: int
    estimated_tokens: int
    token_budget: int
    budget_utilization_pct: float
    summarized_message_count: int = 0
    tokens_saved: int = 0
    compression_ratio: float = 0.0
    pruned_tool_outputs: int = 0
    duration_ms: float = 0.0


@dataclass(frozen=True, kw_only=True)
class ContextStatusEvent(AgentEvent):
    """Event: Periodic context health report."""

    event_type: EventType = EventType.CONTEXT_STATUS
    conversation_id: str
    current_tokens: int
    token_budget: int
    occupancy_pct: float
    compression_level: str
    token_distribution: dict[str, int] = field(default_factory=dict)


# Re-export commonly used event types for convenience
__all__ = [
    "ActDeltaEvent",
    "ActEvent",
    "AgentEvent",
    "ClarificationAnsweredEvent",
    "ClarificationAskedEvent",
    "CompactNeededEvent",
    "CompleteEvent",
    "ContextCompressedEvent",
    "ContextStatusEvent",
    "CostUpdateEvent",
    "DecisionAnsweredEvent",
    "DecisionAskedEvent",
    "DoomLoopDetectedEvent",
    "DoomLoopIntervenedEvent",
    "ErrorEvent",
    "MessageEvent",
    "ObserveEvent",
    "PermissionAskedEvent",
    "PermissionRepliedEvent",
    "RetryEvent",
    "StartEvent",
    "StatusEvent",
    "TextDeltaEvent",
    "TextEndEvent",
    "TextStartEvent",
    "ThoughtDeltaEvent",
    "ThoughtEvent",
]
