"""Domain events for the Agent system.

This module defines the strongly-typed domain events emitted by the Agent during execution.
These events are decoupled from infrastructure concerns (like SSE or Database storage).
"""

import time
from enum import Enum
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field


class AgentEventType(str, Enum):
    """Event types for agent communication."""

    # Status events
    STATUS = "status"
    START = "start"
    COMPLETE = "complete"
    ERROR = "error"

    # Thinking events
    THOUGHT = "thought"
    THOUGHT_DELTA = "thought_delta"

    # Work plan events (multi-level thinking)
    WORK_PLAN = "work_plan"
    STEP_START = "step_start"
    STEP_END = "step_end"
    STEP_FINISH = "step_finish"

    # Tool events
    ACT = "act"
    OBSERVE = "observe"

    # Text events
    TEXT_START = "text_start"
    TEXT_DELTA = "text_delta"
    TEXT_END = "text_end"

    # Message events
    MESSAGE = "message"
    USER_MESSAGE = "user_message"
    ASSISTANT_MESSAGE = "assistant_message"

    # Permission events
    PERMISSION_ASKED = "permission_asked"
    PERMISSION_REPLIED = "permission_replied"

    # Doom loop events
    DOOM_LOOP_DETECTED = "doom_loop_detected"
    DOOM_LOOP_INTERVENED = "doom_loop_intervened"

    # Human interaction events
    CLARIFICATION_ASKED = "clarification_asked"
    CLARIFICATION_ANSWERED = "clarification_answered"
    DECISION_ASKED = "decision_asked"
    DECISION_ANSWERED = "decision_answered"

    # Cost events
    COST_UPDATE = "cost_update"

    # Retry events
    RETRY = "retry"

    # Context events
    COMPACT_NEEDED = "compact_needed"
    CONTEXT_COMPRESSED = "context_compressed"

    # Pattern events
    PATTERN_MATCH = "pattern_match"

    # Skill execution events (L2 layer direct execution)
    SKILL_MATCHED = "skill_matched"
    SKILL_EXECUTION_START = "skill_execution_start"
    SKILL_EXECUTION_COMPLETE = "skill_execution_complete"
    SKILL_FALLBACK = "skill_fallback"

    # Plan Mode events
    PLAN_MODE_ENTER = "plan_mode_enter"
    PLAN_MODE_EXIT = "plan_mode_exit"
    PLAN_CREATED = "plan_created"
    PLAN_UPDATED = "plan_updated"
    PLAN_STATUS_CHANGED = "plan_status_changed"

    # Title generation events
    TITLE_GENERATED = "title_generated"


class AgentDomainEvent(BaseModel):
    """Base class for all agent domain events."""

    event_type: AgentEventType
    timestamp: float = Field(default_factory=time.time)

    class Config:
        frozen = True  # Immutable events

    def to_event_dict(self) -> Dict[str, Any]:
        """
        Convert to SSE/event dictionary format for streaming.

        This provides a unified serialization method for all domain events,
        producing the format expected by WebSocket/SSE clients.

        Returns:
            Dictionary with keys: type, data, timestamp
        """
        from datetime import datetime

        return {
            "type": self.event_type.value,
            "data": self.model_dump(exclude={"event_type", "timestamp"}),
            "timestamp": datetime.fromtimestamp(self.timestamp).isoformat(),
        }


# === Status Events ===


class AgentStatusEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.STATUS
    status: str


class AgentStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.START


class AgentCompleteEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.COMPLETE
    result: Optional[Any] = None
    trace_url: Optional[str] = None


class AgentErrorEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.ERROR
    message: str
    code: Optional[str] = None


# === Thinking Events ===


class AgentThoughtEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.THOUGHT
    content: str
    thought_level: str = "task"
    step_index: Optional[int] = None


class AgentThoughtDeltaEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.THOUGHT_DELTA
    delta: str


# === Work Plan Events ===


class AgentWorkPlanEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.WORK_PLAN
    plan: Dict[str, Any]  # Using Dict for now as Plan is complex


class AgentStepStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.STEP_START
    step_index: int
    description: str


class AgentStepEndEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.STEP_END
    step_index: int
    status: str = "completed"


class AgentStepFinishEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.STEP_FINISH
    tokens: Dict[str, int]
    cost: float
    finish_reason: str
    trace_url: Optional[str] = None


# === Tool Events ===


class AgentActEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.ACT
    tool_name: str
    tool_input: Optional[Dict[str, Any]] = None
    call_id: Optional[str] = None
    status: str = "running"


class AgentObserveEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.OBSERVE
    tool_name: str
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    call_id: Optional[str] = None
    status: str = "completed"


# === Text Events ===


class AgentTextStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_START


class AgentTextDeltaEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_DELTA
    delta: str


class AgentTextEndEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_END
    full_text: Optional[str] = None


# === Message Events ===


class AgentMessageEvent(AgentDomainEvent):
    event_type: AgentEventType = Field(default=AgentEventType.MESSAGE)
    role: str
    content: str

    def __init__(self, **data):
        # Set event_type based on role
        if "event_type" not in data:
            role = data.get("role", "")
            if role == "user":
                data["event_type"] = AgentEventType.USER_MESSAGE
            elif role == "assistant":
                data["event_type"] = AgentEventType.ASSISTANT_MESSAGE
            else:
                data["event_type"] = AgentEventType.MESSAGE
        super().__init__(**data)


# === Permission Events ===


class AgentPermissionAskedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PERMISSION_ASKED
    request_id: str
    permission: str
    patterns: List[str]
    metadata: Dict[str, Any] = Field(default_factory=dict)


class AgentPermissionRepliedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PERMISSION_REPLIED
    request_id: str
    granted: bool


# === Doom Loop Events ===


class AgentDoomLoopDetectedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DOOM_LOOP_DETECTED
    tool: str
    input: Dict[str, Any]


class AgentDoomLoopIntervenedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DOOM_LOOP_INTERVENED
    request_id: str
    action: str


# === Human Interaction Events ===


class AgentClarificationAskedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CLARIFICATION_ASKED
    request_id: str
    question: str
    clarification_type: str
    options: List[Dict[str, Any]]
    allow_custom: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentClarificationAnsweredEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CLARIFICATION_ANSWERED
    request_id: str
    answer: str


class AgentDecisionAskedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DECISION_ASKED
    request_id: str
    question: str
    decision_type: str
    options: List[Dict[str, Any]]
    allow_custom: bool = False
    default_option: Optional[str] = None
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentDecisionAnsweredEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DECISION_ANSWERED
    request_id: str
    decision: str


# === Cost Events ===


class AgentCostUpdateEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.COST_UPDATE
    cost: float
    tokens: Dict[str, int]


# === Retry Events ===


class AgentRetryEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.RETRY
    attempt: int
    delay_ms: int
    message: str


# === Context Events ===


class AgentCompactNeededEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.COMPACT_NEEDED


class AgentContextCompressedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CONTEXT_COMPRESSED
    was_compressed: bool
    compression_strategy: str
    original_message_count: int
    final_message_count: int
    estimated_tokens: int
    token_budget: int
    budget_utilization_pct: float
    summarized_message_count: int = 0


# === Pattern Events ===


class AgentPatternMatchEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PATTERN_MATCH
    pattern_id: str
    pattern_name: str
    confidence: float


# === Skill Events ===


class AgentSkillMatchedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_MATCHED
    skill_id: str
    skill_name: str
    tools: List[str]
    match_score: float
    execution_mode: str


class AgentSkillExecutionStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_EXECUTION_START
    skill_id: str
    skill_name: str
    tools: List[str]
    query: str


class AgentSkillExecutionCompleteEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_EXECUTION_COMPLETE
    skill_id: str
    skill_name: str
    success: bool
    tool_results: List[Any]
    execution_time_ms: int
    summary: Optional[str] = None
    error: Optional[str] = None


class AgentSkillFallbackEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_FALLBACK
    skill_name: str
    reason: str
    error: Optional[str] = None


# === Plan Mode Events ===


class AgentPlanModeEnterEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PLAN_MODE_ENTER
    conversation_id: str
    plan_id: str
    plan_title: str


class AgentPlanModeExitEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PLAN_MODE_EXIT
    conversation_id: str
    plan_id: str
    plan_status: str
    approved: bool


class AgentPlanCreatedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PLAN_CREATED
    plan_id: str
    title: str
    conversation_id: str


class AgentPlanUpdatedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PLAN_UPDATED
    plan_id: str
    content: str
    version: int


class AgentPlanStatusChangedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PLAN_STATUS_CHANGED
    plan_id: str
    old_status: str
    new_status: str


# === Title Generation Events ===


class AgentTitleGeneratedEvent(AgentDomainEvent):
    """Event emitted when a conversation title is generated.

    This event is published after the chat completes and a title
    is generated for the conversation (either by LLM or fallback).
    """
    event_type: AgentEventType = AgentEventType.TITLE_GENERATED
    conversation_id: str
    title: str
    message_id: Optional[str] = None
    generated_by: str = "llm"  # "llm" or "fallback"


# =========================================================================
# Event Type Utilities
# =========================================================================


def get_frontend_event_types() -> List[str]:
    """Get all event type values for frontend TypeScript generation.

    This function is used to generate the TypeScript AgentEventType type
    to ensure Python and TypeScript are always in sync.

    Returns:
        List of event type strings that should be exposed to frontend

    Example:
        >>> get_frontend_event_types()
        ['status', 'start', 'complete', 'error', 'thought', ...]
    """
    # Internal events that should not be exposed to frontend
    internal_events = {
        AgentEventType.COMPACT_NEEDED,  # Internal compression signal
    }

    return [et.value for et in AgentEventType if et not in internal_events]


def get_event_type_docstring() -> str:
    """Get documentation for all event types for code generation.

    Returns:
        Multiline string documenting each event type
    """
    docs = []
    for event_class in [
        AgentStatusEvent,
        AgentStartEvent,
        AgentCompleteEvent,
        AgentErrorEvent,
        AgentThoughtEvent,
        AgentThoughtDeltaEvent,
        AgentWorkPlanEvent,
        AgentStepStartEvent,
        AgentStepEndEvent,
        AgentStepFinishEvent,
        AgentActEvent,
        AgentObserveEvent,
        AgentTextStartEvent,
        AgentTextDeltaEvent,
        AgentTextEndEvent,
        AgentMessageEvent,
        AgentPermissionAskedEvent,
        AgentPermissionRepliedEvent,
        AgentClarificationAskedEvent,
        AgentClarificationAnsweredEvent,
        AgentDecisionAskedEvent,
        AgentDecisionAnsweredEvent,
        AgentCostUpdateEvent,
        AgentContextCompressedEvent,
        AgentPatternMatchEvent,
        AgentSkillMatchedEvent,
        AgentSkillExecutionStartEvent,
        AgentSkillExecutionCompleteEvent,
        AgentSkillFallbackEvent,
        AgentPlanModeEnterEvent,
        AgentPlanModeExitEvent,
        AgentPlanCreatedEvent,
        AgentPlanUpdatedEvent,
        AgentPlanStatusChangedEvent,
        AgentTitleGeneratedEvent,
    ]:
        docs.append(f"{event_class.event_type.value}: {event_class.__doc__}")

    return "\n".join(docs)
