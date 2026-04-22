"""Agent API schemas.

All request/response models for the Agent API endpoints.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.domain.model.agent import Conversation

# === Conversation Schemas ===


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    project_id: str
    title: str | None = "New Conversation"
    agent_config: dict[str, Any] | None = None


class UpdateConversationTitleRequest(BaseModel):
    """Request to update conversation title."""

    title: str


class UpdateConversationConfigRequest(BaseModel):
    """Request to update conversation-level LLM configuration.

    Allows persisting per-conversation model override and LLM parameter overrides.
    These are loaded as defaults for every chat turn in this conversation, but can be
    overridden per-request via ``app_model_context``.
    """

    llm_model_override: str | None = Field(
        None,
        description="Model name to use for this conversation (e.g. 'gpt-4o', 'gemini-2.0-flash'). "
        "Set to empty string or null to clear the override.",
    )
    llm_overrides: dict[str, Any] | None = Field(
        None,
        description="LLM parameter overrides (temperature, max_tokens, top_p, etc.). "
        "Set to null to clear. Keys with null values are removed individually.",
    )


class UpdateConversationModeRequest(BaseModel):
    """Request to update a conversation's mode.

    The ``conversation_mode`` field is optional — omit to leave unchanged.

    Goal and budget constraints for AUTONOMOUS mode are sourced from the
    linked Workspace / WorkspaceTask (Track G); this endpoint no longer
    accepts a ``goal_contract`` payload.
    """

    conversation_mode: str | None = Field(
        default=None,
        description="One of: single_agent, multi_agent_shared, multi_agent_isolated, "
        "autonomous. Omit to leave unchanged; pass null to fall back to project default.",
    )


class ConversationResponse(BaseModel):
    """Response with conversation details."""

    id: str
    project_id: str
    user_id: str
    tenant_id: str
    title: str
    status: str
    message_count: int
    created_at: str
    updated_at: str | None = None
    summary: str | None = None
    agent_config: dict[str, Any] | None = None
    conversation_mode: str | None = None

    @classmethod
    def from_domain(cls, conversation: Conversation) -> "ConversationResponse":
        """Create response from domain entity."""
        return cls(
            id=conversation.id,
            project_id=conversation.project_id,
            user_id=conversation.user_id,
            tenant_id=conversation.tenant_id,
            title=conversation.title,
            status=conversation.status.value,
            message_count=conversation.message_count,
            created_at=conversation.created_at.isoformat(),
            updated_at=conversation.updated_at.isoformat() if conversation.updated_at else None,
            summary=conversation.summary,
            agent_config=conversation.agent_config or None,
            conversation_mode=(
                conversation.conversation_mode.value
                if conversation.conversation_mode is not None
                else None
            ),
        )


class PaginatedConversationsResponse(BaseModel):
    """Paginated response for conversation listing."""

    items: list[ConversationResponse]
    total: int
    has_more: bool
    offset: int
    limit: int


class ChatRequest(BaseModel):
    """Request to chat with the agent."""

    conversation_id: str
    message: str
    reply_to_id: str | None = None
    app_model_context: dict[str, Any] | None = Field(
        None,
        description="Context injected by MCP Apps via ui/update-model-context (SEP-1865)",
    )


# === Tool Schemas ===


class ToolInfo(BaseModel):
    """Information about an available tool."""

    name: str
    description: str


class ToolsListResponse(BaseModel):
    """Response with list of available tools."""

    tools: list[ToolInfo]


class CapabilityDomainSummary(BaseModel):
    """Domain-level capability summary."""

    domain: str
    tool_count: int


class PluginRuntimeCapabilitySummary(BaseModel):
    """Plugin runtime capability counts."""

    plugins_total: int
    plugins_enabled: int
    tool_factories: int
    registered_tool_factories: int
    channel_types: int
    hook_handlers: int
    commands: int
    services: int
    providers: int


class CapabilitySummaryResponse(BaseModel):
    """Response with aggregated capability catalog summary."""

    total_tools: int
    core_tools: int
    domain_breakdown: list[CapabilityDomainSummary]
    plugin_runtime: PluginRuntimeCapabilitySummary


class ToolCompositionResponse(BaseModel):
    """Response model for a tool composition."""

    id: str
    name: str
    description: str
    tools: list[str]
    execution_template: dict[str, Any]
    success_rate: float
    success_count: int
    failure_count: int
    usage_count: int
    created_at: str
    updated_at: str


class ToolCompositionsListResponse(BaseModel):
    """Response model for listing tool compositions."""

    compositions: list[ToolCompositionResponse]
    total: int


# === Workflow Pattern Schemas ===


class PatternStepResponse(BaseModel):
    """Response model for a pattern step."""

    step_number: int
    description: str
    tool_name: str
    expected_output_format: str
    similarity_threshold: float
    tool_parameters: dict[str, Any] | None = None


class WorkflowPatternResponse(BaseModel):
    """Response model for a workflow pattern."""

    id: str
    tenant_id: str
    name: str
    description: str
    steps: list[PatternStepResponse]
    success_rate: float
    usage_count: int
    created_at: str
    updated_at: str
    metadata: dict[str, Any] | None = None


class PatternsListResponse(BaseModel):
    """Response model for patterns list."""

    patterns: list[WorkflowPatternResponse]
    total: int
    page: int
    page_size: int


class ResetPatternsResponse(BaseModel):
    """Response model for pattern reset."""

    deleted_count: int
    tenant_id: str


# === Tenant Config Schemas ===


class RuntimeHookConfigResponse(BaseModel):
    """Response model for a configured runtime hook override."""

    hook_name: str
    plugin_name: str
    hook_family: str | None = None
    executor_kind: str = "builtin"
    source_ref: str | None = None
    entrypoint: str | None = None
    enabled: bool = True
    priority: int | None = None
    settings: dict[str, Any] = Field(default_factory=dict)


class HookCatalogEntryResponse(BaseModel):
    """Response model for a runtime hook available in the registry."""

    hook_name: str
    plugin_name: str
    hook_family: str
    display_name: str
    description: str | None = None
    default_priority: int
    default_enabled: bool = True
    default_executor_kind: str = "builtin"
    default_source_ref: str | None = None
    default_entrypoint: str | None = None
    default_settings: dict[str, Any] = Field(default_factory=dict)
    settings_schema: dict[str, Any] = Field(default_factory=dict)


class HookCatalogResponse(BaseModel):
    """Response model for the runtime hook catalog."""

    hooks: list[HookCatalogEntryResponse]


class RuntimeHookConfigRequest(BaseModel):
    """Request model for a configured runtime hook override."""

    hook_name: str = Field(..., min_length=1, max_length=100)
    plugin_name: str = Field(default="", max_length=100)
    hook_family: str | None = Field(default=None, min_length=1, max_length=50)
    executor_kind: str = Field(default="builtin", min_length=1, max_length=20)
    source_ref: str | None = Field(default=None, min_length=1, max_length=300)
    entrypoint: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool = True
    priority: int | None = Field(default=None, ge=-1000, le=1000)
    settings: dict[str, Any] = Field(default_factory=dict)


class TenantAgentConfigResponse(BaseModel):
    """Response model for tenant agent configuration."""

    id: str
    tenant_id: str
    config_type: str
    llm_model: str
    llm_temperature: float
    pattern_learning_enabled: bool
    multi_level_thinking_enabled: bool
    max_work_plan_steps: int
    tool_timeout_seconds: int
    enabled_tools: list[str]
    disabled_tools: list[str]
    runtime_hooks: list[RuntimeHookConfigResponse]
    runtime_hook_settings_redacted: bool = False
    multi_agent_enabled: bool = False
    created_at: str
    updated_at: str


class UpdateTenantAgentConfigRequest(BaseModel):
    """Request model for updating tenant agent configuration."""

    llm_model: str | None = None
    llm_temperature: float | None = None
    pattern_learning_enabled: bool | None = None
    multi_level_thinking_enabled: bool | None = None
    max_work_plan_steps: int | None = None
    tool_timeout_seconds: int | None = None
    enabled_tools: list[str] | None = None
    disabled_tools: list[str] | None = None
    runtime_hooks: list[RuntimeHookConfigRequest] | None = Field(default=None, max_length=32)


# === Execution Stats Schemas ===


class ExecutionStatsResponse(BaseModel):
    """Response model for execution statistics."""

    total_executions: int
    completed_count: int
    failed_count: int
    average_duration_ms: float
    tool_usage: dict[str, int]
    status_distribution: dict[str, int]
    timeline_data: list[dict[str, Any]]


# === HITL Schemas ===


class HITLRequestResponse(BaseModel):
    """Response model for a pending HITL request."""

    id: str
    conversation_id: str
    message_id: str
    request_type: str
    question: str
    options: list[Any] | None = None
    context: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    created_at: str
    expires_at: str | None = None
    status: str


class PendingHITLResponse(BaseModel):
    """Response model for pending HITL requests."""

    requests: list[HITLRequestResponse]
    total: int


class ClarificationResponseRequest(BaseModel):
    """Request to respond to a clarification request."""

    request_id: str
    response: str


class DecisionResponseRequest(BaseModel):
    """Request to respond to a decision request."""

    request_id: str
    selected_option: str


class DoomLoopResponseRequest(BaseModel):
    """Request to respond to a doom loop detection."""

    request_id: str
    action: str  # "continue", "stop", "modify"


class EnvVarResponseRequest(BaseModel):
    """Request to respond to an environment variable request."""

    request_id: str
    values: dict[str, str]


class HumanInteractionResponse(BaseModel):
    """Response for human interaction endpoints."""

    success: bool
    message: str


# === Unified HITL Schemas (Ray-based) ===


class HITLResponseRequest(BaseModel):
    """Unified request to respond to any HITL request via Redis Stream.

    This replaces separate clarification/decision/env_var endpoints
    with a single unified endpoint consumed by Ray Actors.
    """

    request_id: str
    hitl_type: str  # "clarification", "decision", "env_var", "permission"
    response_data: dict[str, Any]  # Type-specific response data

    # For clarification: {"answer": "user answer"}
    # For decision: {"decision": "option_id"}
    # For env_var: {"values": {"VAR_NAME": "value"}, "save": true}
    # For permission: {"action": "allow", "remember": false}


class HITLCancelRequest(BaseModel):
    """Request to cancel a pending HITL request."""

    request_id: str
    reason: str | None = None


# === Plan Mode Schemas ===


class EnterPlanModeRequest(BaseModel):
    """Request to enter Plan Mode."""

    conversation_id: str
    title: str
    description: str | None = None


class ExitPlanModeRequest(BaseModel):
    """Request to exit Plan Mode."""

    conversation_id: str
    plan_id: str
    approve: bool = True
    summary: str | None = None


class UpdatePlanRequest(BaseModel):
    """Request to update a plan."""

    content: str | None = None
    title: str | None = None
    explored_files: list[str] | None = None
    critical_files: list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None


class PlanResponse(BaseModel):
    """Response with plan details."""

    id: str
    conversation_id: str
    title: str
    content: str
    status: str
    version: int
    metadata: dict[str, Any]
    created_at: str
    updated_at: str


class PlanModeStatusResponse(BaseModel):
    """Response with plan mode status."""

    is_in_plan_mode: bool
    current_mode: str
    current_plan_id: str | None = None
    plan: PlanResponse | None = None


# === Event Replay Schemas ===


class EventReplayResponse(BaseModel):
    """Response with replay events."""

    events: list[dict[str, Any]]
    has_more: bool


class RecoveryInfo(BaseModel):
    """Information needed for event stream recovery."""

    can_recover: bool = False
    stream_exists: bool = False
    recovery_source: str = "none"  # "stream", "database", or "none"
    missed_events_count: int = 0


class ExecutionStatusResponse(BaseModel):
    """Response with execution status and optional recovery information."""

    is_running: bool
    last_event_time_us: int
    last_event_counter: int
    current_message_id: str | None = None
    conversation_id: str
    recovery: RecoveryInfo | None = None


class WorkflowStatusResponse(BaseModel):
    """Response with Ray actor status."""

    workflow_id: str
    run_id: str | None = None
    status: str  # RUNNING, COMPLETED, FAILED, CANCELED, etc.
    started_at: datetime | None = None
    completed_at: datetime | None = None
    current_step: int | None = None
    total_steps: int | None = None
    error: str | None = None


# === Command Schemas ===


class CommandArgInfo(BaseModel):
    """Command argument specification for API response."""

    name: str
    description: str
    arg_type: str
    required: bool = False
    choices: list[str] | None = None


class CommandInfo(BaseModel):
    """Single command definition for API response."""

    name: str
    description: str
    category: str
    scope: str
    aliases: list[str] = Field(default_factory=list)
    args: list[CommandArgInfo] = Field(default_factory=list)


class CommandsListResponse(BaseModel):
    """Response for listing available commands."""

    commands: list[CommandInfo]
    total: int


# === Tool Policy Debug Schemas ===


class ToolPolicyDebugRequest(BaseModel):
    """Request parameters for tool policy debug evaluation."""

    tool_names: list[str] = Field(..., min_length=1, description="Tool names to evaluate")
    depth: int = Field(0, ge=0, description="Agent depth in hierarchy (0 = root)")
    max_depth: int = Field(3, ge=1, description="Maximum allowed depth")
    sandbox_scope: str = Field("agent", description="Sandbox scope: session, agent, shared")
    sandbox_allowed_tools: list[str] | None = Field(
        None, description="Tools allowed by sandbox (None = unrestricted)"
    )
    sandbox_denied_tools: list[str] | None = Field(None, description="Tools denied by sandbox")
    agent_allowed_tools: list[str] | None = Field(
        None, description="Tools allowed by agent config (None = unrestricted)"
    )
    agent_denied_tools: list[str] | None = Field(None, description="Tools denied by agent config")


class ToolPolicyReportItem(BaseModel):
    """Per-tool policy evaluation result."""

    tool_name: str
    allowed: bool
    denial_reason: str | None = None


class PolicyLayerSummary(BaseModel):
    """Summary of a single policy layer."""

    source: str
    precedence: int
    allowed: list[str] | None = None
    denied: list[str] = Field(default_factory=list)


class ToolPolicyDebugResponse(BaseModel):
    """Response for tool policy debug evaluation."""

    role: str
    sandbox_scope: str
    can_spawn: bool
    denied_by_role: list[str]
    policies: list[PolicyLayerSummary]
    tool_reports: list[ToolPolicyReportItem]
    total_tools: int
    allowed_count: int
    denied_count: int


# --- SubAgent Run / Trace Schemas ---


class SubAgentRunResponse(BaseModel):
    """Single SubAgent run detail."""

    run_id: str
    conversation_id: str
    subagent_name: str
    task: str
    status: str
    created_at: str
    started_at: str | None = None
    ended_at: str | None = None
    summary: str | None = None
    error: str | None = None
    execution_time_ms: int | None = None
    tokens_used: int | None = None
    metadata: dict[str, str | int | float | bool | None] = Field(default_factory=dict)
    frozen_result_text: str | None = None
    frozen_at: str | None = None
    trace_id: str | None = None
    parent_span_id: str | None = None
    announce_state: str | None = None


class SubAgentRunListResponse(BaseModel):
    """List of SubAgent runs for a conversation."""

    conversation_id: str
    runs: list[SubAgentRunResponse]
    total: int


class TenantSubAgentRunListResponse(BaseModel):
    """List of SubAgent runs aggregated for a tenant."""

    tenant_id: str
    runs: list[SubAgentRunResponse]
    total: int


class TraceChainResponse(BaseModel):
    """Execution chain grouped by trace_id."""

    trace_id: str
    conversation_id: str
    runs: list[SubAgentRunResponse]
    total: int


class DescendantTreeResponse(BaseModel):
    """Descendant tree for a parent run."""

    parent_run_id: str
    conversation_id: str
    descendants: list[SubAgentRunResponse]
    total: int


class ActiveRunCountResponse(BaseModel):
    """Active run count (global or per-conversation)."""

    active_count: int
    conversation_id: str | None = None


class TenantActiveRunCountResponse(BaseModel):
    """Active run count aggregated for a tenant."""

    tenant_id: str
    active_count: int
