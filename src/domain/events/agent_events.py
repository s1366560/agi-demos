"""Domain events for the Agent system.

This module defines the strongly-typed domain events emitted by the Agent during execution.
These events are decoupled from infrastructure concerns (like SSE or Database storage).

Note: AgentEventType is imported from types.py (Single Source of Truth).
"""

import time
from typing import Any

from pydantic import BaseModel, Field

from src.domain.events.event_dicts import SSEEventDict

# Import AgentEventType from the unified types module (Single Source of Truth)
from src.domain.events.types import AgentEventType, get_frontend_event_types

# Re-export for backward compatibility
__all__ = [
    "AgentArtifactCloseEvent",
    "AgentArtifactOpenEvent",
    "AgentArtifactUpdateEvent",
    "AgentDomainEvent",
    "AgentElicitationAnsweredEvent",
    "AgentElicitationAskedEvent",
    "AgentEventType",
    "AgentMCPAppRegisteredEvent",
    "AgentMCPAppResultEvent",
    "AgentSuggestionsEvent",
    "get_frontend_event_types",
]


class AgentDomainEvent(BaseModel):
    """Base class for all agent domain events."""

    event_type: AgentEventType
    timestamp: float = Field(default_factory=time.time)

    class Config:
        frozen = True  # Immutable events

    def to_event_dict(self) -> SSEEventDict:
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
    result: Any | None = None
    trace_url: str | None = None


class AgentErrorEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.ERROR
    message: str
    code: str | None = None


# === Thinking Events ===


class AgentThoughtEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.THOUGHT
    content: str
    thought_level: str = "task"
    step_index: int | None = None


class AgentThoughtDeltaEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.THOUGHT_DELTA
    delta: str


# === Tool Events ===


class AgentActEvent(AgentDomainEvent):
    """Event: Agent calls a tool.

    The tool_execution_id uniquely identifies this tool execution and
    is used to match with the corresponding AgentObserveEvent.
    """

    event_type: AgentEventType = AgentEventType.ACT
    tool_name: str
    tool_input: dict[str, Any] | None = None
    call_id: str | None = None
    status: str = "running"
    tool_execution_id: str | None = None  # New field for act/observe matching


class AgentActDeltaEvent(AgentDomainEvent):
    """Event: Streaming tool call argument fragments.

    Emitted progressively as tool call arguments are received from the LLM.
    Allows frontend to show tool preparation state before execution begins.
    """

    event_type: AgentEventType = AgentEventType.ACT_DELTA
    tool_name: str
    call_id: str | None = None
    arguments_fragment: str = ""
    accumulated_arguments: str = ""
    status: str = "preparing"


class AgentObserveEvent(AgentDomainEvent):
    """Event: Tool execution result.

    The tool_execution_id must match the corresponding AgentActEvent
    for reliable act/observe pairing in the frontend.
    """

    event_type: AgentEventType = AgentEventType.OBSERVE
    tool_name: str
    result: Any | None = None
    error: str | None = None
    duration_ms: int | None = None
    call_id: str | None = None
    status: str = "completed"
    tool_execution_id: str | None = None  # New field for act/observe matching
    ui_metadata: dict[str, Any] | None = None  # MCP App UI metadata (resourceUri, etc.)


# === Text Events ===


class AgentTextStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_START


class AgentTextDeltaEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_DELTA
    delta: str


class AgentTextEndEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TEXT_END
    full_text: str | None = None


# === Message Events ===


class AgentMessageEvent(AgentDomainEvent):
    event_type: AgentEventType = Field(default=AgentEventType.MESSAGE)
    role: str
    content: str
    attachment_ids: list[str] | None = None
    file_metadata: list[dict[str, Any]] | None = None
    forced_skill_name: str | None = None

    def __init__(self, **data) -> None:
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
    patterns: list[str]
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentPermissionRepliedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.PERMISSION_REPLIED
    request_id: str
    granted: bool


# === Doom Loop Events ===


class AgentDoomLoopDetectedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DOOM_LOOP_DETECTED
    tool: str
    input: dict[str, Any]


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
    options: list[dict[str, Any]]
    allow_custom: bool = True
    context: dict[str, Any] = Field(default_factory=dict)


class AgentClarificationAnsweredEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CLARIFICATION_ANSWERED
    request_id: str
    answer: str


class AgentDecisionAskedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DECISION_ASKED
    request_id: str
    question: str
    decision_type: str
    options: list[dict[str, Any]]
    allow_custom: bool = False
    default_option: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


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
    fields: list[dict[str, Any]]  # List of EnvVarField dicts
    context: dict[str, Any] = Field(default_factory=dict)


class AgentEnvVarProvidedEvent(AgentDomainEvent):
    """Event: User provided environment variable values."""

    event_type: AgentEventType = AgentEventType.ENV_VAR_PROVIDED
    request_id: str
    tool_name: str
    saved_variables: list[str]


# === Cost Events ===


class AgentCostUpdateEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.COST_UPDATE
    cost: float
    tokens: dict[str, int]


# === Retry Events ===


class AgentRetryEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.RETRY
    attempt: int
    delay_ms: int
    message: str


# === Context Events ===


class AgentCompactNeededEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.COMPACT_NEEDED
    compression_level: str = ""
    current_tokens: int = 0
    token_budget: int = 0
    occupancy_pct: float = 0.0


class AgentContextCompressedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CONTEXT_COMPRESSED
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
    token_distribution: dict[str, int] = {}
    compression_history_summary: dict[str, Any] = {}


class AgentContextStatusEvent(AgentDomainEvent):
    """Periodic context health report emitted at start of each step."""

    event_type: AgentEventType = AgentEventType.CONTEXT_STATUS
    current_tokens: int
    token_budget: int
    occupancy_pct: float
    compression_level: str
    token_distribution: dict[str, int] = {}
    compression_history_summary: dict[str, Any] = {}


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
    tools: list[str]
    match_score: float
    execution_mode: str


class AgentSkillExecutionStartEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_EXECUTION_START
    skill_id: str
    skill_name: str
    tools: list[str]
    query: str


class AgentSkillExecutionCompleteEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_EXECUTION_COMPLETE
    skill_id: str
    skill_name: str
    success: bool
    tool_results: list[Any]
    execution_time_ms: int
    summary: str | None = None
    error: str | None = None


class AgentSkillFallbackEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.SKILL_FALLBACK
    skill_name: str
    reason: str
    error: str | None = None


# === Title Generation Events ===


class AgentTitleGeneratedEvent(AgentDomainEvent):
    """Event emitted when a conversation title is generated.

    This event is published after the chat completes and a title
    is generated for the conversation (either by LLM or fallback).
    """

    event_type: AgentEventType = AgentEventType.TITLE_GENERATED
    conversation_id: str
    title: str
    message_id: str | None = None
    generated_by: str = "llm"  # "llm" or "fallback"


# === Sandbox Events ===


class AgentSandboxCreatedEvent(AgentDomainEvent):
    """Event emitted when a sandbox is created."""

    event_type: AgentEventType = AgentEventType.SANDBOX_CREATED
    sandbox_id: str
    project_id: str
    status: str
    endpoint: str | None = None
    websocket_url: str | None = None


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
    url: str | None = None
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
    url: str | None = None
    display: str = ""
    resolution: str = ""
    port: int = 0


class AgentTerminalStartedEvent(AgentDomainEvent):
    """Event emitted when terminal service is started."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STARTED
    sandbox_id: str
    url: str | None = None
    port: int = 7681
    session_id: str | None = None
    pid: int | None = None


class AgentTerminalStoppedEvent(AgentDomainEvent):
    """Event emitted when terminal service is stopped."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STOPPED
    sandbox_id: str
    session_id: str | None = None


class AgentTerminalStatusEvent(AgentDomainEvent):
    """Event emitted with current terminal status."""

    event_type: AgentEventType = AgentEventType.TERMINAL_STATUS
    sandbox_id: str
    running: bool
    url: str | None = None
    port: int = 0
    session_id: str | None = None
    pid: int | None = None


# === Artifact Events ===


class AgentSuggestionsEvent(AgentDomainEvent):
    """Event: Agent provides follow-up suggestions after completing a response."""

    event_type: AgentEventType = AgentEventType.SUGGESTIONS
    suggestions: list[str]


class ArtifactInfo(BaseModel):
    """Artifact information for event payloads."""

    id: str
    filename: str
    mime_type: str
    category: str  # ArtifactCategory value
    size_bytes: int
    url: str | None = None
    preview_url: str | None = None
    source_tool: str | None = None
    metadata: dict[str, Any] = {}


class AgentArtifactCreatedEvent(AgentDomainEvent):
    """Event emitted when an artifact is detected and upload started.

    This event is emitted immediately when a new file is detected in the
    sandbox output directory or extracted from tool output, before the upload completes.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACT_CREATED
    artifact_id: str
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    filename: str
    mime_type: str
    category: str
    size_bytes: int
    url: str | None = None  # URL if already available
    preview_url: str | None = None
    source_tool: str | None = None
    source_path: str | None = None


class AgentArtifactReadyEvent(AgentDomainEvent):
    """Event emitted when an artifact is fully uploaded and accessible.

    This event provides the final URL(s) for accessing the artifact.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACT_READY
    artifact_id: str
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    filename: str
    mime_type: str
    category: str
    size_bytes: int
    url: str
    preview_url: str | None = None
    source_tool: str | None = None
    metadata: dict[str, Any] = {}


class AgentArtifactErrorEvent(AgentDomainEvent):
    """Event emitted when artifact processing fails."""

    event_type: AgentEventType = AgentEventType.ARTIFACT_ERROR
    artifact_id: str
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    filename: str
    error: str


class AgentArtifactsBatchEvent(AgentDomainEvent):
    """Event emitted with multiple artifacts at once (e.g., after tool completion).

    This is useful for efficiently sending multiple artifacts discovered
    after a tool execution completes.
    """

    event_type: AgentEventType = AgentEventType.ARTIFACTS_BATCH
    sandbox_id: str | None = None
    tool_execution_id: str | None = None
    artifacts: list[ArtifactInfo] = []
    source_tool: str | None = None


class AgentArtifactOpenEvent(AgentDomainEvent):
    """Event: Agent opens content in the canvas panel."""

    event_type: AgentEventType = AgentEventType.ARTIFACT_OPEN
    artifact_id: str
    title: str
    content: str
    content_type: str = "code"  # code, markdown, preview, data
    language: str | None = None


class AgentArtifactUpdateEvent(AgentDomainEvent):
    """Event: Agent updates content in an open canvas tab."""

    event_type: AgentEventType = AgentEventType.ARTIFACT_UPDATE
    artifact_id: str
    content: str
    append: bool = False  # True to append, False to replace


class AgentArtifactCloseEvent(AgentDomainEvent):
    """Event: Agent closes a canvas tab."""

    event_type: AgentEventType = AgentEventType.ARTIFACT_CLOSE
    artifact_id: str


# === MCP App Events ===


class AgentMCPAppResultEvent(AgentDomainEvent):
    """Event: An MCP tool with interactive UI was called.

    Carries the tool result alongside the resolved HTML resource
    for rendering in the Canvas panel as a sandboxed iframe.
    """

    event_type: AgentEventType = AgentEventType.MCP_APP_RESULT
    app_id: str
    tool_name: str
    tool_result: Any | None = None
    tool_input: dict[str, Any] | None = None
    resource_html: str
    resource_uri: str
    ui_metadata: dict[str, Any] = Field(default_factory=dict)
    tool_execution_id: str | None = None
    project_id: str = ""
    server_name: str = ""
    structured_content: dict[str, Any] | None = None


class AgentMCPAppRegisteredEvent(AgentDomainEvent):
    """Event: A new MCP App was auto-detected during tool discovery.

    Emitted when SandboxMCPServerManager discovers tools with
    _meta.ui.resourceUri, whether from user-added or agent-developed servers.
    """

    event_type: AgentEventType = AgentEventType.MCP_APP_REGISTERED
    app_id: str
    server_name: str
    tool_name: str
    source: str  # "user_added" | "agent_developed"
    resource_uri: str
    title: str | None = None


# =========================================================================
# Task List Events
# =========================================================================


class AgentTaskListUpdatedEvent(AgentDomainEvent):
    """Event: Full task list replaced for a conversation."""

    event_type: AgentEventType = AgentEventType.TASK_LIST_UPDATED
    conversation_id: str
    tasks: list[dict[str, Any]]


class AgentTaskUpdatedEvent(AgentDomainEvent):
    """Event: Single task status/content changed."""

    event_type: AgentEventType = AgentEventType.TASK_UPDATED
    conversation_id: str
    task_id: str
    status: str
    content: str | None = None


class AgentTaskStartEvent(AgentDomainEvent):
    """Event: Agent started working on a task (timeline event)."""

    event_type: AgentEventType = AgentEventType.TASK_START
    task_id: str
    content: str
    order_index: int
    total_tasks: int


class AgentTaskCompleteEvent(AgentDomainEvent):
    """Event: Agent completed a task (timeline event)."""

    event_type: AgentEventType = AgentEventType.TASK_COMPLETE
    task_id: str
    status: str
    order_index: int
    total_tasks: int


# =========================================================================
# Tool Update Events (real-time tool hot-plug)
# =========================================================================


class AgentToolsUpdatedEvent(AgentDomainEvent):
    """Event: New tools were registered and are now available.

    Emitted when RegisterMCPServerTool successfully registers new MCP tools,
    enabling the frontend to immediately update the available tools list
    without requiring an additional round-trip.

    This event signals that:
    1. New MCP server was installed and started
    2. Tools were discovered successfully
    3. The agent's tool cache was invalidated
    4. Frontend should refresh its tool list
    """

    event_type: AgentEventType = AgentEventType.TOOLS_UPDATED
    project_id: str = ""
    tool_names: list[str] = Field(default_factory=list)
    server_name: str = ""
    requires_refresh: bool = True  # Frontend should refresh tool list


# =========================================================================
# Progress Events (long-running operation updates)
# =========================================================================


class AgentProgressEvent(AgentDomainEvent):
    """Event: Progress update for a long-running tool operation.

    Emitted when MCP tools report progress during execution using the
    progress notification mechanism defined in the MCP protocol.

    This enables real-time progress tracking in the frontend for operations
    like file transfers, code generation, or other long-running tasks.
    """

    event_type: AgentEventType = AgentEventType.PROGRESS
    tool_name: str
    progress_token: str  # Unique identifier for tracking this progress
    progress: float  # Current progress value
    total: float | None = None  # Total value (if known)
    message: str | None = None  # Human-readable progress message


# =========================================================================
# MCP Elicitation Events (MCP server -> user information requests)
# =========================================================================


class AgentElicitationAskedEvent(AgentDomainEvent):
    """Event: MCP server requests information from user via elicitation.

    Emitted when an MCP server needs to request structured information
    from the user through the agent. This integrates MCP elicitation
    with the existing HITL (Human-in-the-Loop) system.

    MCP servers use elicitation to request information that wasn't
    provided in the original tool call, such as API keys, configuration
    values, or user preferences.

    The requested_schema follows JSON Schema format and describes what
    information the server is requesting from the user.
    """

    event_type: AgentEventType = AgentEventType.ELICITATION_ASKED
    request_id: str
    server_id: str
    server_name: str
    message: str  # Human-readable message from the MCP server
    requested_schema: dict[str, Any]  # JSON Schema describing the requested data


class AgentElicitationAnsweredEvent(AgentDomainEvent):
    """Event: User provided response to MCP elicitation request.

    Emitted when the user responds to an elicitation request from an MCP server.
    The response contains the data requested according to the schema.
    """

    event_type: AgentEventType = AgentEventType.ELICITATION_ANSWERED
    request_id: str
    response: dict[str, Any]  # User's response matching the requested schema


# =========================================================================
# Memory Events (auto-recall / auto-capture)
# =========================================================================


class AgentMemoryRecalledEvent(AgentDomainEvent):
    """Emitted when memories are recalled for context injection."""

    event_type: AgentEventType = AgentEventType.MEMORY_RECALLED
    memories: list[dict[str, Any]]
    count: int
    search_ms: int


class AgentMemoryCapturedEvent(AgentDomainEvent):
    """Emitted when new memories are captured from conversation."""

    event_type: AgentEventType = AgentEventType.MEMORY_CAPTURED
    captured_count: int
    categories: list[str]


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
        AgentActEvent,
        AgentActDeltaEvent,
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
        AgentSuggestionsEvent,
        AgentArtifactOpenEvent,
        AgentArtifactUpdateEvent,
        AgentArtifactCloseEvent,
        AgentMemoryRecalledEvent,
        AgentMemoryCapturedEvent,
    ]:
        docs.append(f"{event_class.event_type.value}: {event_class.__doc__}")

    return "\n".join(docs)
