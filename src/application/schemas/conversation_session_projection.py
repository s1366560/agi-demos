"""Typed response contract for a scoped cloud conversation session."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _ProjectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @field_validator("*", mode="before")
    @classmethod
    def _normalize_utc_datetimes(cls, value: object) -> object:
        if not isinstance(value, datetime):
            return value
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SessionConversationResponse(_ProjectionModel):
    id: str
    tenant_id: str
    project_id: str
    workspace_id: str | None
    linked_workspace_task_id: str | None
    workspace_name: str | None
    user_id: str
    title: str
    summary: str | None
    status: str
    current_mode: str
    conversation_mode: str | None
    capability_mode: Literal["work", "code"] | None
    message_count: int
    participant_agents: list[str]
    coordinator_agent_id: str | None
    focused_agent_id: str | None
    created_at: datetime
    updated_at: datetime | None


class SessionWorkspaceAttemptResponse(_ProjectionModel):
    id: str
    workspace_task_id: str
    root_goal_task_id: str
    workspace_id: str
    conversation_id: str
    attempt_number: int
    status: str
    worker_agent_id: str | None
    leader_agent_id: str | None
    candidate_summary: str | None
    candidate_artifact_refs: list[str]
    candidate_verification_refs: list[str]
    leader_feedback: str | None
    adjudication_reason: str | None
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None


class SessionExecutionResponse(_ProjectionModel):
    current_attempt: SessionWorkspaceAttemptResponse | None
    attempt_history: list[SessionWorkspaceAttemptResponse]


class SessionConversationTaskResponse(_ProjectionModel):
    id: str
    conversation_id: str
    content: str
    status: str
    priority: str
    order_index: int
    created_at: datetime
    updated_at: datetime | None


class SessionWorkspacePlanNodeResponse(_ProjectionModel):
    id: str
    plan_id: str
    workspace_task_id: str
    kind: str
    title: str
    description: str
    intent: str
    execution: str
    progress: dict[str, Any]
    assignee_agent_id: str | None
    current_attempt_id: str | None
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None


class SessionWorkspacePlanContextResponse(_ProjectionModel):
    id: str
    workspace_id: str
    goal_id: str
    status: str
    created_at: datetime
    updated_at: datetime | None
    linked_nodes: list[SessionWorkspacePlanNodeResponse]


class SessionPendingHITLResponse(_ProjectionModel):
    id: str
    conversation_id: str
    message_id: str | None
    request_type: Literal["clarification", "decision", "env_var", "permission", "a2ui_action"]
    question: str
    options: list[dict[str, Any]]
    context: dict[str, Any]
    metadata: dict[str, Any]
    status: Literal["pending"]
    created_at: datetime
    expires_at: datetime


class SessionArtifactRecordResponse(_ProjectionModel):
    id: str


class SessionToolExecutionResponse(_ProjectionModel):
    id: str
    message_id: str
    call_id: str
    tool_name: str
    status: str
    error: str | None
    step_number: int | None
    sequence_number: int
    started_at: datetime
    completed_at: datetime | None
    duration_ms: int | None


class SessionToolExecutionPageResponse(_ProjectionModel):
    items: list[SessionToolExecutionResponse]
    total: int
    truncated: bool


class SessionEvidenceSummaryResponse(_ProjectionModel):
    candidate_artifact_ref_count: int
    candidate_verification_ref_count: int
    artifact_record_count: int
    tool_execution_record_count: int
    failed_tool_execution_count: int


class SessionCapabilitiesResponse(_ProjectionModel):
    can_send_message: bool
    can_respond_to_hitl: bool
    can_approve_plan: bool
    can_control_execution: bool
    can_review_artifacts: bool
    can_deliver_artifacts: bool
    allowed_actions: list[Literal["send_message", "respond_to_hitl"]]


class ConversationSessionProjectionResponse(_ProjectionModel):
    schema_version: Literal[2] = 2
    projection_kind: Literal["workspace_session"] = "workspace_session"
    authority_kind: Literal["workspace_attempt", "conversation_record"]
    authority_id: str
    conversation: SessionConversationResponse
    execution: SessionExecutionResponse
    conversation_tasks: list[SessionConversationTaskResponse]
    workspace_plan_context: SessionWorkspacePlanContextResponse | None
    pending_hitl: list[SessionPendingHITLResponse]
    artifact_records: list[SessionArtifactRecordResponse]
    tool_execution_records: SessionToolExecutionPageResponse
    evidence_summary: SessionEvidenceSummaryResponse
    capabilities: SessionCapabilitiesResponse
    snapshot_revision: str = Field(min_length=1)
    updated_at: datetime


__all__ = ["ConversationSessionProjectionResponse"]
