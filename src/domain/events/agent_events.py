"""Domain events for the Agent system.

This module defines the strongly-typed domain events emitted by the Agent during execution.
These events are decoupled from infrastructure concerns (like SSE or Database storage).

Note: AgentEventType is imported from types.py (Single Source of Truth).
"""

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# Import AgentEventType from the unified types module (Single Source of Truth)
from src.domain.events.types import AgentEventType, get_frontend_event_types

# Re-export for backward compatibility
__all__ = ["AgentEventType", "AgentDomainEvent", "get_frontend_event_types"]


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
    """Event: Agent calls a tool.

    The tool_execution_id uniquely identifies this tool execution and
    is used to match with the corresponding AgentObserveEvent.
    """

    event_type: AgentEventType = AgentEventType.ACT
    tool_name: str
    tool_input: Optional[Dict[str, Any]] = None
    call_id: Optional[str] = None
    status: str = "running"
    tool_execution_id: Optional[str] = None  # New field for act/observe matching


class AgentObserveEvent(AgentDomainEvent):
    """Event: Tool execution result.

    The tool_execution_id must match the corresponding AgentActEvent
    for reliable act/observe pairing in the frontend.
    """

    event_type: AgentEventType = AgentEventType.OBSERVE
    tool_name: str
    result: Optional[Any] = None
    error: Optional[str] = None
    duration_ms: Optional[int] = None
    call_id: Optional[str] = None
    status: str = "completed"
    tool_execution_id: Optional[str] = None  # New field for act/observe matching


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
    attachment_ids: Optional[List[str]] = None
    file_metadata: Optional[List[Dict[str, Any]]] = None

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


# === Environment Variable Events ===


class AgentEnvVarRequestedEvent(AgentDomainEvent):
    """Event: Agent requests environment variables from user."""

    event_type: AgentEventType = AgentEventType.ENV_VAR_REQUESTED
    request_id: str
    tool_name: str
    fields: List[Dict[str, Any]]  # List of EnvVarField dicts
    context: Dict[str, Any] = Field(default_factory=dict)


class AgentEnvVarProvidedEvent(AgentDomainEvent):
    """Event: User provided environment variable values."""

    event_type: AgentEventType = AgentEventType.ENV_VAR_PROVIDED
    request_id: str
    tool_name: str
    saved_variables: List[str]


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


class AgentPlanExecutionStartEvent(AgentDomainEvent):
    """Event emitted when plan execution starts."""

    event_type: AgentEventType = AgentEventType.PLAN_EXECUTION_START
    plan_id: str
    total_steps: int
    user_query: str


class AgentPlanExecutionCompleteEvent(AgentDomainEvent):
    """Event emitted when plan execution completes."""

    event_type: AgentEventType = AgentEventType.PLAN_EXECUTION_COMPLETE
    plan_id: str
    total_duration_ms: int
    steps_completed: int
    steps_failed: int
    final_status: str


class AgentPlanStepReadyEvent(AgentDomainEvent):
    """Event emitted when a step is ready to execute."""

    event_type: AgentEventType = AgentEventType.PLAN_STEP_READY
    plan_id: str
    step_id: str
    step_number: int
    description: str
    tool_name: str


class AgentPlanStepCompleteEvent(AgentDomainEvent):
    """Event emitted when a step completes."""

    event_type: AgentEventType = AgentEventType.PLAN_STEP_COMPLETE
    plan_id: str
    step_id: str
    status: str
    result: Optional[str] = None
    error: Optional[str] = None


class AgentPlanStepSkippedEvent(AgentDomainEvent):
    """Event emitted when a step is skipped."""

    event_type: AgentEventType = AgentEventType.PLAN_STEP_SKIPPED
    plan_id: str
    step_id: str
    reason: str


class AgentPlanSnapshotCreatedEvent(AgentDomainEvent):
    """Event emitted when a plan snapshot is created."""

    event_type: AgentEventType = AgentEventType.PLAN_SNAPSHOT_CREATED
    plan_id: str
    snapshot_id: str
    snapshot_name: str
    snapshot_type: str


class AgentPlanRollbackEvent(AgentDomainEvent):
    """Event emitted when a plan is rolled back to a snapshot."""

    event_type: AgentEventType = AgentEventType.PLAN_ROLLBACK
    plan_id: str
    snapshot_id: str
    reason: str


class AgentReflectionCompleteEvent(AgentDomainEvent):
    """Event emitted when reflection completes."""

    event_type: AgentEventType = AgentEventType.REFLECTION_COMPLETE
    reflection_id: str
    plan_id: str
    assessment: str
    recommended_action: str
    summary: str
    has_adjustments: bool
    adjustment_count: int


class AgentAdjustmentAppliedEvent(AgentDomainEvent):
    """Event emitted when adjustments are applied to a plan."""

    event_type: AgentEventType = AgentEventType.ADJUSTMENT_APPLIED
    plan_id: str
    adjustment_count: int
    adjustments: List[Dict[str, Any]]


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


# === Sandbox Events ===


class AgentSandboxCreatedEvent(AgentDomainEvent):
    """Event emitted when a sandbox is created."""

    event_type: AgentEventType = AgentEventType.SANDBOX_CREATED
    sandbox_id: str
    project_id: str
    status: str
    endpoint: Optional[str] = None
    websocket_url: Optional[str] = None


class AgentSandboxTerminatedEvent(AgentDomainEvent):
    """Event emitted when a sandbox is terminated."""

    event_type: AgentEventType = AgentEventType.SANDBOX_TERMINATED
    sandbox_id: str


class AgentSandboxStatusEvent(AgentDomainEvent):
    """Event emitted when sandbox status changes."""

    event_type: AgentEventType = AgentEventType.SANDBOX_STATUS
    sandbox_id: str
    status: str


class AgentDesktopStartedEvent(AgentDomainEvent):
    """Event emitted when remote desktop service is started."""

    event_type: AgentEventType = AgentEventType.DESKTOP_STARTED
    sandbox_id: str
    url: Optional[str] = None
    display: str = ":1"
    resolution: str = "1280x720"
    port: int = 6080


class AgentDesktopStoppedEvent(AgentDomainEvent):
    """Event emitted when remote desktop service is stopped."""

    event_type: AgentEventType = AgentEventType.DESKTOP_STOPPED
    sandbox_id: str


class AgentDesktopStatusEvent(AgentDomainEvent):
    """Event emitted with current desktop status."""

    event_type: AgentEventType = AgentEventType.DESKTOP_STATUS
    sandbox_id: str
    running: bool
    url: Optional[str] = None
    display: str = ""
    resolution: str = ""
    port: int = 0


class AgentTerminalStartedEvent(AgentDomainEvent):
    """Event emitted when terminal service is started."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STARTED
    sandbox_id: str
    url: Optional[str] = None
    port: int = 7681
    session_id: Optional[str] = None
    pid: Optional[int] = None


class AgentTerminalStoppedEvent(AgentDomainEvent):
    """Event emitted when terminal service is stopped."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STOPPED
    sandbox_id: str
    session_id: Optional[str] = None


class AgentTerminalStatusEvent(AgentDomainEvent):
    """Event emitted with current terminal status."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STATUS
    sandbox_id: str
    running: bool
    url: Optional[str] = None
    port: int = 0
    session_id: Optional[str] = None
    pid: Optional[int] = None


# === Artifact Events ===


class ArtifactInfo(BaseModel):
    """Artifact information for event payloads."""

    id: str
    filename: str
    mime_type: str
    category: str  # ArtifactCategory value
    size_bytes: int
    url: Optional[str] = None
    preview_url: Optional[str] = None
    source_tool: Optional[str] = None
    metadata: Dict[str, Any] = {}


class AgentArtifactCreatedEvent(AgentDomainEvent):
    """Event emitted when an artifact is detected and upload started.

    This event is emitted immediately when a new file is detected in the
    sandbox output directory or extracted from tool output, before the upload completes.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACT_CREATED
    artifact_id: str
    sandbox_id: Optional[str] = None
    tool_execution_id: Optional[str] = None
    filename: str
    mime_type: str
    category: str
    size_bytes: int
    url: Optional[str] = None  # URL if already available
    preview_url: Optional[str] = None
    source_tool: Optional[str] = None
    source_path: Optional[str] = None


class AgentArtifactReadyEvent(AgentDomainEvent):
    """Event emitted when an artifact is fully uploaded and accessible.

    This event provides the final URL(s) for accessing the artifact.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACT_READY
    artifact_id: str
    sandbox_id: Optional[str] = None
    tool_execution_id: Optional[str] = None
    filename: str
    mime_type: str
    category: str
    size_bytes: int
    url: str
    preview_url: Optional[str] = None
    source_tool: Optional[str] = None
    metadata: Dict[str, Any] = {}


class AgentArtifactErrorEvent(AgentDomainEvent):
    """Event emitted when artifact processing fails."""

    event_type: AgentEventType = AgentEventType.ARTIFACT_ERROR
    artifact_id: str
    sandbox_id: Optional[str] = None
    tool_execution_id: Optional[str] = None
    filename: str
    error: str


class AgentArtifactsBatchEvent(AgentDomainEvent):
    """Event emitted with multiple artifacts at once (e.g., after tool completion).

    This is useful for efficiently sending multiple artifacts discovered
    after a tool execution completes.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACTS_BATCH
    sandbox_id: Optional[str] = None
    tool_execution_id: Optional[str] = None
    artifacts: List[ArtifactInfo] = []
    source_tool: Optional[str] = None


# =========================================================================
# Event Type Utilities
# =========================================================================

# get_frontend_event_types is imported from types.py (Single Source of Truth)


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
        AgentPlanExecutionStartEvent,
        AgentPlanExecutionCompleteEvent,
        AgentPlanStepReadyEvent,
        AgentPlanStepCompleteEvent,
        AgentPlanStepSkippedEvent,
        AgentPlanSnapshotCreatedEvent,
        AgentPlanRollbackEvent,
        AgentReflectionCompleteEvent,
        AgentAdjustmentAppliedEvent,
        AgentTitleGeneratedEvent,
        AgentSandboxCreatedEvent,
        AgentSandboxTerminatedEvent,
        AgentSandboxStatusEvent,
        AgentDesktopStartedEvent,
        AgentDesktopStoppedEvent,
        AgentDesktopStatusEvent,
        AgentTerminalStartedEvent,
        AgentTerminalStoppedEvent,
        AgentTerminalStatusEvent,
        AgentArtifactCreatedEvent,
        AgentArtifactReadyEvent,
        AgentArtifactErrorEvent,
        AgentArtifactsBatchEvent,
    ]:
        docs.append(f"{event_class.event_type.value}: {event_class.__doc__}")

    return "\n".join(docs)
