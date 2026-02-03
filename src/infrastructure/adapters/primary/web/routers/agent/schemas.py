"""Agent API schemas.

All request/response models for the Agent API endpoints.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel

from src.domain.model.agent import Conversation

# === Conversation Schemas ===


class CreateConversationRequest(BaseModel):
    """Request to create a new conversation."""

    project_id: str
    title: Optional[str] = "New Conversation"
    agent_config: Optional[dict] = None


class UpdateConversationTitleRequest(BaseModel):
    """Request to update conversation title."""

    title: str


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
    updated_at: Optional[str] = None

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
        )


class ChatRequest(BaseModel):
    """Request to chat with the agent."""

    conversation_id: str
    message: str


# === Tool Schemas ===


class ToolInfo(BaseModel):
    """Information about an available tool."""

    name: str
    description: str


class ToolsListResponse(BaseModel):
    """Response with list of available tools."""

    tools: list[ToolInfo]


class ToolCompositionResponse(BaseModel):
    """Response model for a tool composition."""

    id: str
    name: str
    description: str
    tools: list[str]
    execution_template: dict
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
    tool_parameters: Optional[dict] = None


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
    metadata: Optional[dict] = None


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
    created_at: str
    updated_at: str


class UpdateTenantAgentConfigRequest(BaseModel):
    """Request model for updating tenant agent configuration."""

    llm_model: Optional[str] = None
    llm_temperature: Optional[float] = None
    pattern_learning_enabled: Optional[bool] = None
    multi_level_thinking_enabled: Optional[bool] = None
    max_work_plan_steps: Optional[int] = None
    tool_timeout_seconds: Optional[int] = None
    enabled_tools: Optional[list[str]] = None
    disabled_tools: Optional[list[str]] = None


# === Execution Stats Schemas ===


class ExecutionStatsResponse(BaseModel):
    """Response model for execution statistics."""

    total_executions: int
    completed_count: int
    failed_count: int
    average_duration_ms: float
    tool_usage: dict[str, int]
    status_distribution: dict[str, int]
    timeline_data: list[dict]


# === HITL Schemas ===


class HITLRequestResponse(BaseModel):
    """Response model for a pending HITL request."""

    id: str
    conversation_id: str
    message_id: str
    request_type: str
    request_data: dict
    created_at: str
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


# === Plan Mode Schemas ===


class EnterPlanModeRequest(BaseModel):
    """Request to enter Plan Mode."""

    conversation_id: str
    title: str
    description: Optional[str] = None


class ExitPlanModeRequest(BaseModel):
    """Request to exit Plan Mode."""

    conversation_id: str
    plan_id: str
    approve: bool = True
    summary: Optional[str] = None


class UpdatePlanRequest(BaseModel):
    """Request to update a plan."""

    content: Optional[str] = None
    title: Optional[str] = None
    explored_files: Optional[list[str]] = None
    critical_files: Optional[list[dict]] = None
    metadata: Optional[dict] = None


class PlanResponse(BaseModel):
    """Response with plan details."""

    id: str
    conversation_id: str
    title: str
    content: str
    status: str
    version: int
    metadata: dict
    created_at: str
    updated_at: str


class PlanModeStatusResponse(BaseModel):
    """Response with plan mode status."""

    is_in_plan_mode: bool
    current_mode: str
    current_plan_id: Optional[str] = None
    plan: Optional[PlanResponse] = None


# === Event Replay Schemas ===


class EventReplayResponse(BaseModel):
    """Response with replay events."""

    events: list[dict]
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
    last_sequence: int
    current_message_id: Optional[str] = None
    conversation_id: str
    recovery: Optional[RecoveryInfo] = None


class WorkflowStatusResponse(BaseModel):
    """Response with Temporal workflow status."""

    workflow_id: str
    run_id: Optional[str] = None
    status: str  # RUNNING, COMPLETED, FAILED, CANCELED, etc.
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    current_step: Optional[int] = None
    total_steps: Optional[int] = None
    error: Optional[str] = None
