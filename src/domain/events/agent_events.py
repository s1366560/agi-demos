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
    "AgentA2UIActionAnsweredEvent",
    "AgentA2UIActionAskedEvent",
    "AgentArtifactCloseEvent",
    "AgentArtifactOpenEvent",
    "AgentArtifactUpdateEvent",
    "AgentBackgroundLaunchedEvent",
    "AgentCanvasUpdatedEvent",
    "AgentCompletedEvent",
    "AgentConflictMarkedEvent",
    "AgentContextSummaryGeneratedEvent",
    "AgentConversationFinishedEvent",
    "AgentDomainEvent",
    "AgentElicitationAnsweredEvent",
    "AgentElicitationAskedEvent",
    "AgentEscalatedEvent",
    "AgentEventType",
    "AgentGoalCompletedEvent",
    "AgentHttpServiceErrorEvent",
    "AgentHttpServiceStartedEvent",
    "AgentHttpServiceStoppedEvent",
    "AgentHttpServiceUpdatedEvent",
    "AgentHumanInputRequestedEvent",
    "AgentMCPAppRegisteredEvent",
    "AgentMCPAppResultEvent",
    "AgentMessageReceivedEvent",
    "AgentMessageSentEvent",
    "AgentParallelCompletedEvent",
    "AgentParallelStartedEvent",
    "AgentPlanSuggestedEvent",
    "AgentPolicyFilteredEvent",
    "AgentProgressDeclaredEvent",
    "AgentSelectionTraceEvent",
    "AgentSpawnedEvent",
    "AgentStoppedEvent",
    "AgentSuggestionsEvent",
    "AgentTaskAssignedEvent",
    "AgentTaskRefusedEvent",
    "BlackboardPostCreatedEvent",
    "BlackboardPostDeletedEvent",
    "BlackboardPostUpdatedEvent",
    "BlackboardReplyCreatedEvent",
    "BlackboardReplyDeletedEvent",
    "ContextCompactedEvent",
    "ConversationParticipantJoinedEvent",
    "ConversationParticipantLeftEvent",
    "GraphHandoffEvent",
    "GraphNodeCompletedEvent",
    "GraphNodeFailedEvent",
    "GraphNodeSkippedEvent",
    "GraphNodeStartedEvent",
    "GraphRunCancelledEvent",
    "GraphRunCompletedEvent",
    "GraphRunFailedEvent",
    "GraphRunStartedEvent",
    "SessionForkedEvent",
    "SessionMergedEvent",
    "SubAgentAnnounceExpiredEvent",
    "SubAgentAnnounceReceivedEvent",
    "SubAgentAnnounceRetryEvent",
    "SubAgentAnnounceSentEvent",
    "SubAgentCompletedEvent",
    "SubAgentDelegationEvent",
    "SubAgentDepthLimitedEvent",
    "SubAgentDoomLoopEvent",
    "SubAgentFailedEvent",
    "SubAgentKilledEvent",
    "SubAgentOrphanDetectedEvent",
    "SubAgentQueuedEvent",
    "SubAgentRoutedEvent",
    "SubAgentSessionUpdateEvent",
    "SubAgentSpawnRejectedEvent",
    "SubAgentSpawningEvent",
    "SubAgentStartedEvent",
    "SubAgentSteeredEvent",
    "ToolPolicyDeniedEvent",
    "TopologyUpdatedEvent",
    "WorkspaceAdjudicationCompleteEvent",
    "WorkspaceAgentBoundEvent",
    "WorkspaceAgentUnboundEvent",
    "WorkspaceDecompositionCompleteEvent",
    "WorkspaceDeletedEvent",
    "WorkspaceGoalCompletedEvent",
    "WorkspaceGoalMaterializedEvent",
    "WorkspaceMemberJoinedEvent",
    "WorkspaceMemberLeftEvent",
    "WorkspaceMessageCreatedEvent",
    "WorkspaceTaskAssignedEvent",
    "WorkspaceTaskCreatedEvent",
    "WorkspaceTaskDeletedEvent",
    "WorkspaceTaskStatusChangedEvent",
    "WorkspaceTaskUpdatedEvent",
    "WorkspaceUpdatedEvent",
    "WorkspaceWorkerDispatchedEvent",
    "WorkspaceWorkerReportSubmittedEvent",
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
    content: str | None = None
    execution_summary: dict[str, Any] | None = None
    skill_used: str | None = None
    subagent_used: str | None = None
    subagent_result: Any | None = None
    orchestration_mode: str | None = None
    subtask_count: int | None = None
    step_count: int | None = None
    session_id: str | None = None
    route_id: str | None = None
    trace_id: str | None = None
    execution_id: str | None = None


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

    def __init__(self, **data: Any) -> None:
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
    default_value: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)


class AgentClarificationAnsweredEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.CLARIFICATION_ANSWERED
    request_id: str
    answer: str | list[str]


class AgentDecisionAskedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DECISION_ASKED
    request_id: str
    question: str
    decision_type: str
    options: list[dict[str, Any]]
    allow_custom: bool = False
    default_option: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    selection_mode: str = "single"
    max_selections: int | None = None


class AgentDecisionAnsweredEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.DECISION_ANSWERED
    request_id: str
    decision: str | list[str]


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
    from_cache: bool = False
    messages_in_summary: int = 0


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


class AgentHttpServiceStartedEvent(AgentDomainEvent):
    """Event emitted when an HTTP service is registered/started for sandbox preview."""

    event_type: AgentEventType = AgentEventType.HTTP_SERVICE_STARTED
    sandbox_id: str | None = None
    service_id: str
    service_name: str
    source_type: str  # sandbox_internal | external_url
    service_url: str
    proxy_url: str | None = None
    ws_proxy_url: str | None = None
    auto_open: bool = True
    restart_token: str | None = None


class AgentHttpServiceUpdatedEvent(AgentDomainEvent):
    """Event emitted when an HTTP service registration is updated."""

    event_type: AgentEventType = AgentEventType.HTTP_SERVICE_UPDATED
    sandbox_id: str | None = None
    service_id: str
    service_name: str
    source_type: str  # sandbox_internal | external_url
    service_url: str
    proxy_url: str | None = None
    ws_proxy_url: str | None = None
    auto_open: bool = True
    restart_token: str | None = None
    status: str = "running"


class AgentHttpServiceStoppedEvent(AgentDomainEvent):
    """Event emitted when an HTTP service is stopped/unregistered."""

    event_type: AgentEventType = AgentEventType.HTTP_SERVICE_STOPPED
    sandbox_id: str | None = None
    service_id: str
    service_name: str
    status: str = "stopped"


class AgentHttpServiceErrorEvent(AgentDomainEvent):
    """Event emitted when an HTTP service enters error state."""

    event_type: AgentEventType = AgentEventType.HTTP_SERVICE_ERROR
    sandbox_id: str | None = None
    service_id: str
    service_name: str
    status: str = "error"
    error_message: str


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
# Canvas Events (A2UI dynamic UI blocks)
# =========================================================================


class AgentCanvasUpdatedEvent(AgentDomainEvent):
    """Event: Canvas block created, updated, or deleted."""

    event_type: AgentEventType = AgentEventType.CANVAS_UPDATED
    conversation_id: str
    block_id: str
    action: str  # "created", "updated", "deleted"
    block: dict[str, Any] | None = None  # Serialised CanvasBlock (None for delete)


class AgentA2UIActionAskedEvent(AgentDomainEvent):
    """Event: An A2UI interactive surface is presented, waiting for user action."""

    event_type: AgentEventType = AgentEventType.A2UI_ACTION_ASKED
    request_id: str
    conversation_id: str
    block_id: str
    title: str = ""
    timeout_seconds: float = 300.0
    surface_data: dict[str, Any] | None = None


class AgentA2UIActionAnsweredEvent(AgentDomainEvent):
    """Event: User interacted with an A2UI surface."""

    event_type: AgentEventType = AgentEventType.A2UI_ACTION_ANSWERED
    request_id: str
    action_name: str = ""
    source_component_id: str = ""
    context: dict[str, Any] = Field(default_factory=dict)


# =========================================================================
# Agent Routing & Orchestration Events
# =========================================================================


class AgentPlanSuggestedEvent(AgentDomainEvent):
    """Event: Agent suggests switching to plan mode."""

    event_type: AgentEventType = AgentEventType.PLAN_SUGGESTED
    plan_id: str
    conversation_id: str
    reason: str
    confidence: float


class AgentContextSummaryGeneratedEvent(AgentDomainEvent):
    """Event: Context summary was generated during compression."""

    event_type: AgentEventType = AgentEventType.CONTEXT_SUMMARY_GENERATED
    summary_text: str
    summary_tokens: int
    messages_covered_count: int
    compression_level: str


class AgentSelectionTraceEvent(AgentDomainEvent):
    """Event: Tool selection trace for debugging."""

    event_type: AgentEventType = AgentEventType.SELECTION_TRACE
    route_id: str | None = None
    trace_id: str | None = None
    initial_count: int = 0
    final_count: int = 0
    removed_total: int = 0
    domain_lane: str | None = None
    tool_budget: int = 0
    budget_exceeded_stages: list[str] = Field(default_factory=list)
    stages: list[dict[str, Any]] = Field(default_factory=list)


class AgentPolicyFilteredEvent(AgentDomainEvent):
    """Event: Policy filter summary for debugging."""

    event_type: AgentEventType = AgentEventType.POLICY_FILTERED
    route_id: str | None = None
    trace_id: str | None = None
    removed_total: int = 0
    stage_count: int = 0
    domain_lane: str | None = None
    tool_budget: int = 0
    budget_exceeded_stages: list[str] = Field(default_factory=list)


class AgentParallelStartedEvent(AgentDomainEvent):
    """Event: Parallel subagent execution started."""

    event_type: AgentEventType = AgentEventType.PARALLEL_STARTED
    task_count: int
    session_id: str | None = None
    route_id: str | None = None
    trace_id: str | None = None
    subtasks: list[dict[str, Any]] = Field(default_factory=list)
    task_ids: list[str] = Field(default_factory=list)


class AgentParallelCompletedEvent(AgentDomainEvent):
    """Event: Parallel subagent execution completed."""

    event_type: AgentEventType = AgentEventType.PARALLEL_COMPLETED
    total_tasks: int
    session_id: str | None = None
    route_id: str | None = None
    trace_id: str | None = None
    completed: int = 0
    all_succeeded: bool = False
    total_tokens: int = 0
    failed_agents: list[str] = Field(default_factory=list)
    succeeded: int = 0
    failed: int = 0
    results: list[Any] = Field(default_factory=list)


class AgentBackgroundLaunchedEvent(AgentDomainEvent):
    """Event: Background subagent execution launched."""

    event_type: AgentEventType = AgentEventType.BACKGROUND_LAUNCHED
    execution_id: str
    subagent_id: str
    subagent_name: str
    task: str


# =========================================================================
# SubAgent Lifecycle Events (L3 layer formal events)
# =========================================================================


class SubAgentSpawningEvent(AgentDomainEvent):
    """Event: SubAgent session is being spawned (pre-start lifecycle hook)."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_SPAWNING
    conversation_id: str
    run_id: str
    subagent_name: str
    spawn_mode: str
    thread_requested: bool = False
    cleanup: str = "auto"
    model_override: str | None = None
    thinking_override: str | None = None


class SubAgentRoutedEvent(AgentDomainEvent):
    """Event: SubAgent was selected by the router for a task."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ROUTED
    subagent_id: str
    subagent_name: str
    task: str
    model: str
    confidence: float = 0.0
    match_reason: str = ""


class SubAgentStartedEvent(AgentDomainEvent):
    """Event: SubAgent execution has started."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_STARTED
    subagent_id: str
    subagent_name: str
    task: str
    model: str


class SubAgentCompletedEvent(AgentDomainEvent):
    """Event: SubAgent execution completed (success or failure)."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_COMPLETED
    subagent_id: str
    subagent_name: str
    success: bool = True
    summary: str = ""
    tool_calls_count: int = 0
    tokens_used: int = 0
    execution_time_ms: int = 0
    error: str | None = None
    final_content: str = ""


class SubAgentFailedEvent(AgentDomainEvent):
    """Event: SubAgent execution failed with an error."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_FAILED
    subagent_id: str
    subagent_name: str
    error: str


class SubAgentDoomLoopEvent(AgentDomainEvent):
    """Event: SubAgent was terminated due to doom loop detection."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_DOOM_LOOP
    subagent_id: str
    subagent_name: str
    reason: str
    threshold: int = 3


class SubAgentRetryEvent(AgentDomainEvent):
    """Event: SubAgent execution is being retried after failure."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_RETRY
    subagent_id: str
    subagent_name: str
    attempt: int
    max_retries: int
    model: str
    reason: str


class SubAgentQueuedEvent(AgentDomainEvent):
    """Event: SubAgent queued, waiting for capacity."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_QUEUED
    subagent_id: str
    subagent_name: str
    queue_position: int = 0
    reason: str = ""  # "depth_limit" | "concurrency_limit"


class SubAgentKilledEvent(AgentDomainEvent):
    """Event: SubAgent forcibly terminated."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_KILLED
    subagent_id: str
    subagent_name: str
    kill_reason: str  # "timeout" | "user_cancel" | "parent_cancel" | "orphan_sweep"


class SubAgentSteeredEvent(AgentDomainEvent):
    """Event: SubAgent received steering instruction from parent."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_STEERED
    subagent_id: str
    subagent_name: str
    instruction: str


class SubAgentDepthLimitedEvent(AgentDomainEvent):
    """Event: SubAgent spawn refused due to depth limit."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_DEPTH_LIMITED
    subagent_name: str
    current_depth: int
    max_depth: int
    parent_subagent_name: str = ""


class SubAgentSessionUpdateEvent(AgentDomainEvent):
    """Event: Progress update from a running SubAgent."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_SESSION_UPDATE
    subagent_id: str
    subagent_name: str
    progress: int = 0  # 0-100
    status_message: str = ""
    tokens_used: int = 0
    tool_calls_count: int = 0


class SubAgentSpawnRejectedEvent(AgentDomainEvent):
    """Event: SubAgent spawn refused by SpawnValidator (non-depth reasons)."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_SPAWN_REJECTED
    subagent_name: str
    rejection_code: str  # SpawnRejectionCode.value
    rejection_reason: str
    requester_id: str = ""
    current_depth: int = 0
    max_depth: int = 0
    active_runs: int = 0
    context: dict[str, Any] = Field(default_factory=dict)


class SubAgentAnnounceRetryEvent(AgentDomainEvent):
    """Event: Child-to-parent announce is being retried."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ANNOUNCE_RETRY
    agent_id: str
    session_id: str
    attempt: int
    max_retries: int
    delay_ms: int
    error: str = ""
    error_category: str = ""  # "transient" | "permanent" | "unknown"


class SubAgentOrphanDetectedEvent(AgentDomainEvent):
    """Event: Orphaned SubAgent run detected during sweep."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ORPHAN_DETECTED
    run_id: str
    subagent_name: str
    conversation_id: str
    reason: str  # "timeout" | "parent_gone" | "cancel_key" | "no_heartbeat"
    age_seconds: float = 0.0
    action_taken: str = ""  # "cancelled" | "marked_failed" | "ignored"


class SubAgentAnnounceSentEvent(AgentDomainEvent):
    """Event: Child SubAgent sent result announcement to parent."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ANNOUNCE_SENT
    agent_id: str
    session_id: str
    parent_agent_id: str
    result_preview: str = ""


class SubAgentAnnounceReceivedEvent(AgentDomainEvent):
    """Event: Parent agent received result announcement from child."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ANNOUNCE_RECEIVED
    agent_id: str
    session_id: str
    from_agent_id: str
    from_agent_name: str = ""
    result_preview: str = ""


class SubAgentAnnounceExpiredEvent(AgentDomainEvent):
    """Event: SubAgent announce operation expired after exhausting retries."""

    event_type: AgentEventType = AgentEventType.SUBAGENT_ANNOUNCE_EXPIRED
    agent_id: str
    session_id: str
    attempts: int
    last_error: str = ""


class ToolPolicyDeniedEvent(AgentDomainEvent):
    event_type: AgentEventType = AgentEventType.TOOL_POLICY_DENIED
    agent_id: str
    tool_name: str
    policy_layer: str = ""
    denial_reason: str = ""


class SubAgentDelegationEvent(AgentDomainEvent):
    """Event: Main agent delegates a task to a SubAgent.

    Emitted when the main agent decides to delegate a task to a specialized
    SubAgent. This provides UX visibility into the delegation flow.
    """

    event_type: AgentEventType = AgentEventType.SUBAGENT_DELEGATION
    conversation_id: str
    from_agent_id: str | None  # None = main agent
    to_subagent_id: str
    to_subagent_name: str
    trigger_type: str  # 'keyword' | 'semantic' | 'explicit'
    task_description: str


class AgentSpawnedEvent(AgentDomainEvent):
    """Event: A parent agent spawned a child agent session."""

    event_type: AgentEventType = AgentEventType.AGENT_SPAWNED
    agent_id: str
    agent_name: str
    parent_agent_id: str
    child_session_id: str
    mode: str = "run"
    task_summary: str = ""


class AgentCompletedEvent(AgentDomainEvent):
    """Event: A child agent completed its task and announced results."""

    event_type: AgentEventType = AgentEventType.AGENT_COMPLETED
    agent_id: str
    agent_name: str
    parent_agent_id: str
    session_id: str
    result: str = ""
    success: bool = True
    artifacts: list[str] = Field(default_factory=list)


class AgentMessageSentEvent(AgentDomainEvent):
    """Event: An agent sent a message to another agent."""

    event_type: AgentEventType = AgentEventType.AGENT_MESSAGE_SENT
    from_agent_id: str
    to_agent_id: str
    from_agent_name: str = ""
    to_agent_name: str = ""
    message_preview: str = ""


class AgentMessageReceivedEvent(AgentDomainEvent):
    """Event: An agent received a message from another agent."""

    event_type: AgentEventType = AgentEventType.AGENT_MESSAGE_RECEIVED
    agent_id: str
    agent_name: str
    from_agent_id: str
    from_agent_name: str = ""
    message_preview: str = ""


class AgentStoppedEvent(AgentDomainEvent):
    """Event: An agent was stopped."""

    event_type: AgentEventType = AgentEventType.AGENT_STOPPED
    agent_id: str
    agent_name: str
    reason: str = ""
    stopped_by: str = ""


# === Context Engine & Session Lifecycle Events (Phase 3) ===


class ContextCompactedEvent(AgentDomainEvent):
    """Event: Context window was compacted to fit token budget."""

    event_type: AgentEventType = AgentEventType.CONTEXT_COMPACTED
    conversation_id: str
    before_tokens: int
    after_tokens: int


class SessionForkedEvent(AgentDomainEvent):
    """Event: A conversation session was forked into a child session."""

    event_type: AgentEventType = AgentEventType.SESSION_FORKED
    parent_conversation_id: str
    child_conversation_id: str


class SessionMergedEvent(AgentDomainEvent):
    """Event: A child session was merged back into the parent session."""

    event_type: AgentEventType = AgentEventType.SESSION_MERGED
    parent_conversation_id: str
    child_conversation_id: str
    merge_strategy: str


# =========================================================================
# Graph Orchestration Events (multi-agent DAG execution)
# =========================================================================


class GraphRunStartedEvent(AgentDomainEvent):
    """Event: A graph orchestration run was started."""

    event_type: AgentEventType = AgentEventType.GRAPH_RUN_STARTED
    graph_run_id: str
    graph_id: str
    graph_name: str
    pattern: str
    entry_node_ids: list[str] = Field(default_factory=list)


class GraphRunCompletedEvent(AgentDomainEvent):
    """Event: A graph orchestration run completed successfully."""

    event_type: AgentEventType = AgentEventType.GRAPH_RUN_COMPLETED
    graph_run_id: str
    graph_id: str
    graph_name: str
    total_steps: int
    duration_seconds: float | None = None


class GraphRunFailedEvent(AgentDomainEvent):
    """Event: A graph orchestration run failed."""

    event_type: AgentEventType = AgentEventType.GRAPH_RUN_FAILED
    graph_run_id: str
    graph_id: str
    graph_name: str
    error_message: str
    failed_node_id: str | None = None


class GraphRunCancelledEvent(AgentDomainEvent):
    """Event: A graph orchestration run was cancelled."""

    event_type: AgentEventType = AgentEventType.GRAPH_RUN_CANCELLED
    graph_run_id: str
    graph_id: str
    graph_name: str
    reason: str = ""


class GraphNodeStartedEvent(AgentDomainEvent):
    """Event: A node in the graph started execution."""

    event_type: AgentEventType = AgentEventType.GRAPH_NODE_STARTED
    graph_run_id: str
    node_id: str
    node_label: str
    agent_definition_id: str
    agent_session_id: str | None = None


class GraphNodeCompletedEvent(AgentDomainEvent):
    """Event: A node in the graph completed execution."""

    event_type: AgentEventType = AgentEventType.GRAPH_NODE_COMPLETED
    graph_run_id: str
    node_id: str
    node_label: str
    output_keys: list[str] = Field(default_factory=list)
    duration_seconds: float | None = None


class GraphNodeFailedEvent(AgentDomainEvent):
    """Event: A node in the graph failed execution."""

    event_type: AgentEventType = AgentEventType.GRAPH_NODE_FAILED
    graph_run_id: str
    node_id: str
    node_label: str
    error_message: str


class GraphNodeSkippedEvent(AgentDomainEvent):
    """Event: A node in the graph was skipped."""

    event_type: AgentEventType = AgentEventType.GRAPH_NODE_SKIPPED
    graph_run_id: str
    node_id: str
    node_label: str
    reason: str = ""


class GraphHandoffEvent(AgentDomainEvent):
    """Event: An agent handed off execution to another agent in a Swarm pattern."""

    event_type: AgentEventType = AgentEventType.GRAPH_HANDOFF
    graph_run_id: str
    from_node_id: str
    to_node_id: str
    from_label: str = ""
    to_label: str = ""
    context_summary: str = ""


# =========================================================================
# Workspace Collaboration Events
# =========================================================================


class WorkspaceMemberJoinedEvent(AgentDomainEvent):
    """Event: A member joined a workspace."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_MEMBER_JOINED
    workspace_id: str
    member_id: str
    member_role: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMemberLeftEvent(AgentDomainEvent):
    """Event: A member left a workspace."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_MEMBER_LEFT
    workspace_id: str
    member_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)


# =========================================================================
# Multi-agent conversation participant events (Track B, P2-3 phase-2)
# =========================================================================


class ConversationParticipantJoinedEvent(AgentDomainEvent):
    """Event: An agent joined a multi-agent conversation roster."""

    event_type: AgentEventType = AgentEventType.CONVERSATION_PARTICIPANT_JOINED
    conversation_id: str
    agent_id: str
    actor_id: str | None = None  # user or agent that performed the add
    role: str | None = None  # "coordinator" | "participant" | "focused" (optional hint)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConversationParticipantLeftEvent(AgentDomainEvent):
    """Event: An agent left a multi-agent conversation roster."""

    event_type: AgentEventType = AgentEventType.CONVERSATION_PARTICIPANT_LEFT
    conversation_id: str
    agent_id: str
    actor_id: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


# =========================================================================
# Multi-agent structured action events (Track B · Agent First action toolset)
#
# These events form the structured "decision log" for every subjective
# multi-agent decision. Each event is emitted by exactly one tool call;
# the domain layer treats them as an append-only audit record of who
# decided what, when, and why (prose reason — never a code lookup).
# =========================================================================


class AgentTaskAssignedEvent(AgentDomainEvent):
    """Coordinator assigned a task to a target agent."""

    event_type: AgentEventType = AgentEventType.AGENT_TASK_ASSIGNED
    conversation_id: str
    actor_agent_id: str
    target_agent_id: str
    task_title: str
    rationale: str
    task_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentTaskRefusedEvent(AgentDomainEvent):
    """Worker refused an assigned task with a prose reason."""

    event_type: AgentEventType = AgentEventType.AGENT_TASK_REFUSED
    conversation_id: str
    actor_agent_id: str
    task_id: str | None = None
    reason: str = ""
    suggested_reassignment: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentHumanInputRequestedEvent(AgentDomainEvent):
    """Agent judged that human input is required and raised a request.

    Carries the **agent-declared** HITL category plus the audit-only
    ``rationale`` / ``proposed_fallback`` prose (Track B · Agent First).
    The backend never classifies category itself — it only applies the
    structural ``blocking_categories ∩ side_effects`` upgrade.
    """

    event_type: AgentEventType = AgentEventType.AGENT_HUMAN_INPUT_REQUESTED
    conversation_id: str
    actor_agent_id: str
    question: str
    urgency: str = "normal"  # normal | high | blocking
    context: str = ""
    category: str = "informational"  # HitlCategory value (agent-declared)
    rationale: str = ""
    proposed_fallback: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDecisionLoggedEvent(AgentDomainEvent):
    """Audit marker for a judgmental tool-call (Agent First).

    Emitted alongside every multi-agent action tool + supervisor
    ``verdict``. Persisted to ``decision_logs``.
    """

    event_type: AgentEventType = AgentEventType.AGENT_DECISION_LOGGED
    conversation_id: str
    actor_agent_id: str
    tool_name: str
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_summary: str = ""
    rationale: str = ""
    latency_ms: int = -1
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentEscalatedEvent(AgentDomainEvent):
    """Agent escalated an issue to coordinator or human."""

    event_type: AgentEventType = AgentEventType.AGENT_ESCALATED
    conversation_id: str
    actor_agent_id: str
    escalated_to: str  # "coordinator" | "human" | an agent_id
    reason: str = ""
    severity: str = "medium"  # low | medium | high | critical
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentConflictMarkedEvent(AgentDomainEvent):
    """Agent flagged a conflict / disagreement that needs resolution."""

    event_type: AgentEventType = AgentEventType.AGENT_CONFLICT_MARKED
    conversation_id: str
    actor_agent_id: str
    conflict_with: str  # agent_id, artifact_id, decision_ref, etc.
    summary: str = ""
    evidence: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentProgressDeclaredEvent(AgentDomainEvent):
    """Agent reported progress on an assigned task."""

    event_type: AgentEventType = AgentEventType.AGENT_PROGRESS_DECLARED
    conversation_id: str
    actor_agent_id: str
    task_id: str | None = None
    status: str = "in_progress"  # in_progress | blocked | done | needs_review
    summary: str = ""
    percent_complete: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentGoalCompletedEvent(AgentDomainEvent):
    """Coordinator (or solo agent) declared the top-level goal complete."""

    event_type: AgentEventType = AgentEventType.AGENT_GOAL_COMPLETED
    conversation_id: str
    actor_agent_id: str
    summary: str = ""
    artifacts: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentSupervisorVerdictEvent(AgentDomainEvent):
    """Supervisor agent's structured verdict on conversation health.

    Emitted by the `verdict` tool. The ``status`` field mirrors
    :class:`VerdictStatus` as a string — we keep it string-typed on the
    event payload so serialization stays stable across schema migrations.
    """

    event_type: AgentEventType = AgentEventType.AGENT_SUPERVISOR_VERDICT
    conversation_id: str
    actor_agent_id: str
    status: str  # one of healthy | stalled | looping | goal_drift | budget_risk
    rationale: str = ""
    recommended_actions: list[str] = Field(default_factory=list)
    trigger: str = "tick"  # tick | doom_loop | stale | budget
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentConversationFinishedEvent(AgentDomainEvent):
    """Conversation terminated by one of the three gates: goal, budget, or safety.

    Emitted by the termination evaluator when any gate fires. The ``reason``
    field is a structured enum (TerminationReason); ``rationale`` is the
    deterministic arithmetic / membership check that fired the gate.

    Carries ``terminal_state`` (snapshot of budget caps + supervisor verdict +
    cost counters) for audit trail and resumable_state (autonomous mode).
    """

    event_type: AgentEventType = AgentEventType.AGENT_CONVERSATION_FINISHED
    conversation_id: str
    reason: str  # TerminationReason enum value
    actor: str = "system"
    rationale: str = ""
    terminal_state: dict[str, Any] = Field(default_factory=dict)
    resumable_state: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceUpdatedEvent(AgentDomainEvent):
    """Event: Workspace settings or metadata were updated."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_UPDATED
    workspace_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class WorkspaceDeletedEvent(AgentDomainEvent):
    """Event: A workspace was deleted."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_DELETED
    workspace_id: str


class WorkspaceAgentBoundEvent(AgentDomainEvent):
    """Event: An agent was bound to a workspace."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_AGENT_BOUND
    workspace_id: str
    agent_id: str
    workspace_agent_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceAgentUnboundEvent(AgentDomainEvent):
    """Event: An agent was unbound from a workspace."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_AGENT_UNBOUND
    workspace_id: str
    agent_id: str
    workspace_agent_id: str | None = None


class BlackboardPostCreatedEvent(AgentDomainEvent):
    """Event: A new blackboard post was created."""

    event_type: AgentEventType = AgentEventType.BLACKBOARD_POST_CREATED
    workspace_id: str
    post_id: str
    author_id: str | None = None
    title: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlackboardPostUpdatedEvent(AgentDomainEvent):
    """Event: A blackboard post was updated."""

    event_type: AgentEventType = AgentEventType.BLACKBOARD_POST_UPDATED
    workspace_id: str
    post_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class BlackboardPostDeletedEvent(AgentDomainEvent):
    """Event: A blackboard post was deleted."""

    event_type: AgentEventType = AgentEventType.BLACKBOARD_POST_DELETED
    workspace_id: str
    post_id: str


class BlackboardReplyCreatedEvent(AgentDomainEvent):
    """Event: A reply was added to a blackboard post."""

    event_type: AgentEventType = AgentEventType.BLACKBOARD_REPLY_CREATED
    workspace_id: str
    post_id: str
    reply_id: str
    author_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BlackboardReplyDeletedEvent(AgentDomainEvent):
    """Event: A reply was deleted from a blackboard post."""

    event_type: AgentEventType = AgentEventType.BLACKBOARD_REPLY_DELETED
    workspace_id: str
    post_id: str
    reply_id: str


class WorkspaceTaskCreatedEvent(AgentDomainEvent):
    """Event: A workspace task was created."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_TASK_CREATED
    workspace_id: str
    task_id: str
    title: str | None = None
    assignee_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceTaskUpdatedEvent(AgentDomainEvent):
    """Event: A workspace task was updated."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_TASK_UPDATED
    workspace_id: str
    task_id: str
    changes: dict[str, Any] = Field(default_factory=dict)


class WorkspaceTaskDeletedEvent(AgentDomainEvent):
    """Event: A workspace task was deleted."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_TASK_DELETED
    workspace_id: str
    task_id: str


class WorkspaceTaskStatusChangedEvent(AgentDomainEvent):
    """Event: A workspace task status was changed."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_TASK_STATUS_CHANGED
    workspace_id: str
    task_id: str
    old_status: str | None = None
    new_status: str
    changed_by: str | None = None


class WorkspaceTaskAssignedEvent(AgentDomainEvent):
    """Event: A workspace task was assigned to an agent or user."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_TASK_ASSIGNED
    workspace_id: str
    task_id: str
    task: dict[str, Any] | None = None
    assignee_id: str | None = None
    assignee_user_id: str | None = None
    assignee_agent_id: str | None = None
    workspace_agent_id: str | None = None
    status: str | None = None
    assigned_by: str | None = None


class TopologyUpdatedEvent(AgentDomainEvent):
    """Event: Workspace topology (nodes/edges) was updated."""

    event_type: AgentEventType = AgentEventType.TOPOLOGY_UPDATED
    workspace_id: str
    action: str = ""
    node_id: str | None = None
    edge_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkspaceMessageCreatedEvent(AgentDomainEvent):
    """Event: A chat message was created in a workspace."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_MESSAGE_CREATED
    workspace_id: str
    message_id: str
    sender_id: str
    sender_type: str = "human"
    content: str = ""
    mentions: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Workspace Orchestration Lifecycle Events
# ---------------------------------------------------------------------------


class WorkspaceGoalMaterializedEvent(AgentDomainEvent):
    """Event: A workspace goal has been materialized and is ready for decomposition."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_GOAL_MATERIALIZED
    workspace_id: str
    goal_id: str
    goal_description: str = ""


class WorkspaceDecompositionCompleteEvent(AgentDomainEvent):
    """Event: Goal decomposition finished; subtasks are ready for dispatch."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_DECOMPOSITION_COMPLETE
    workspace_id: str
    goal_id: str
    subtask_ids: list[str] = Field(default_factory=list)
    subtask_count: int = 0


class WorkspaceWorkerDispatchedEvent(AgentDomainEvent):
    """Event: A worker agent has been dispatched to execute a subtask."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_WORKER_DISPATCHED
    workspace_id: str
    task_id: str
    worker_agent_id: str = ""
    attempt_id: str = ""


class WorkspaceWorkerReportSubmittedEvent(AgentDomainEvent):
    """Event: A worker agent submitted its execution report for leader adjudication."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_WORKER_REPORT_SUBMITTED
    workspace_id: str
    task_id: str
    attempt_id: str = ""
    worker_agent_id: str = ""
    status: str = ""


class WorkspaceAdjudicationCompleteEvent(AgentDomainEvent):
    """Event: Leader adjudication of a worker report is complete."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_ADJUDICATION_COMPLETE
    workspace_id: str
    task_id: str
    attempt_id: str = ""
    verdict: str = ""
    next_task_id: str | None = None


class WorkspaceGoalCompletedEvent(AgentDomainEvent):
    """Event: All subtasks are done and the workspace goal is complete."""

    event_type: AgentEventType = AgentEventType.WORKSPACE_GOAL_COMPLETED
    workspace_id: str
    goal_id: str
    final_status: str = ""
    completed_subtask_count: int = 0
    total_subtask_count: int = 0


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
        AgentCanvasUpdatedEvent,
        AgentPlanSuggestedEvent,
        AgentContextSummaryGeneratedEvent,
        AgentSelectionTraceEvent,
        AgentPolicyFilteredEvent,
        AgentParallelStartedEvent,
        AgentParallelCompletedEvent,
        AgentBackgroundLaunchedEvent,
        SubAgentSpawningEvent,
        SubAgentRoutedEvent,
        SubAgentStartedEvent,
        SubAgentCompletedEvent,
        SubAgentFailedEvent,
        SubAgentDoomLoopEvent,
        SubAgentRetryEvent,
        SubAgentQueuedEvent,
        SubAgentKilledEvent,
        SubAgentSteeredEvent,
        SubAgentDepthLimitedEvent,
        SubAgentSessionUpdateEvent,
        SubAgentSpawnRejectedEvent,
        SubAgentAnnounceRetryEvent,
        SubAgentOrphanDetectedEvent,
        SubAgentAnnounceSentEvent,
        SubAgentAnnounceReceivedEvent,
        SubAgentAnnounceExpiredEvent,
        AgentSpawnedEvent,
        AgentCompletedEvent,
        AgentMessageSentEvent,
        AgentMessageReceivedEvent,
        AgentStoppedEvent,
        ContextCompactedEvent,
        SessionForkedEvent,
        SessionMergedEvent,
        GraphRunStartedEvent,
        GraphRunCompletedEvent,
        GraphRunFailedEvent,
        GraphRunCancelledEvent,
        GraphNodeStartedEvent,
        GraphNodeCompletedEvent,
        GraphNodeFailedEvent,
        GraphNodeSkippedEvent,
        GraphHandoffEvent,
        WorkspaceMemberJoinedEvent,
        WorkspaceMemberLeftEvent,
        WorkspaceUpdatedEvent,
        WorkspaceDeletedEvent,
        WorkspaceAgentBoundEvent,
        WorkspaceAgentUnboundEvent,
        BlackboardPostCreatedEvent,
        BlackboardPostUpdatedEvent,
        BlackboardPostDeletedEvent,
        BlackboardReplyCreatedEvent,
        BlackboardReplyDeletedEvent,
        WorkspaceTaskCreatedEvent,
        WorkspaceTaskUpdatedEvent,
        WorkspaceTaskDeletedEvent,
        WorkspaceTaskStatusChangedEvent,
        WorkspaceTaskAssignedEvent,
        TopologyUpdatedEvent,
        WorkspaceMessageCreatedEvent,
        WorkspaceGoalMaterializedEvent,
        WorkspaceDecompositionCompleteEvent,
        WorkspaceWorkerDispatchedEvent,
        WorkspaceWorkerReportSubmittedEvent,
        WorkspaceAdjudicationCompleteEvent,
        WorkspaceGoalCompletedEvent,
    ]:
        docs.append(f"{event_class.event_type.value}: {event_class.__doc__}")  # type: ignore[attr-defined]

    return "\n".join(docs)
