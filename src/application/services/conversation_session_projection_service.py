"""Build a conversation projection from persisted cloud authority records."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from src.application.schemas.conversation_session_projection import (
    ConversationSessionProjectionResponse,
    SessionArtifactRecordResponse,
    SessionCapabilitiesResponse,
    SessionConversationResponse,
    SessionConversationTaskResponse,
    SessionEvidenceSummaryResponse,
    SessionExecutionResponse,
    SessionPendingHITLResponse,
    SessionToolExecutionPageResponse,
    SessionToolExecutionResponse,
    SessionWorkspaceAttemptResponse,
    SessionWorkspacePlanContextResponse,
    SessionWorkspacePlanNodeResponse,
)

HITLKind = Literal["clarification", "decision", "env_var", "permission", "a2ui_action"]
CapabilityMode = Literal["work", "code"]


class ConversationSessionNotFoundError(Exception):
    """Raised when the complete requested resource scope is not visible."""


@dataclass(frozen=True, kw_only=True)
class ConversationAuthority:
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
    capability_mode: CapabilityMode | None
    message_count: int
    participant_agents: tuple[str, ...]
    coordinator_agent_id: str | None
    focused_agent_id: str | None
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class WorkspaceAttemptAuthority:
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
    candidate_artifact_refs: tuple[str, ...]
    candidate_verification_refs: tuple[str, ...]
    leader_feedback: str | None
    adjudication_reason: str | None
    created_at: datetime
    updated_at: datetime | None
    completed_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class ConversationTaskAuthority:
    id: str
    conversation_id: str
    content: str
    status: str
    priority: str
    order_index: int
    created_at: datetime
    updated_at: datetime | None


@dataclass(frozen=True, kw_only=True)
class WorkspacePlanNodeAuthority:
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


@dataclass(frozen=True, kw_only=True)
class WorkspacePlanContextAuthority:
    id: str
    workspace_id: str
    goal_id: str
    status: str
    created_at: datetime
    updated_at: datetime | None
    linked_nodes: tuple[WorkspacePlanNodeAuthority, ...]


@dataclass(frozen=True, kw_only=True)
class PendingHITLAuthority:
    id: str
    conversation_id: str
    message_id: str | None
    request_type: HITLKind
    question: str
    options: tuple[dict[str, Any], ...]
    context: dict[str, Any]
    metadata: dict[str, Any]
    created_at: datetime
    expires_at: datetime


@dataclass(frozen=True, kw_only=True)
class ArtifactRecordAuthority:
    id: str
    created_at: datetime


@dataclass(frozen=True, kw_only=True)
class ToolExecutionAuthority:
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


@dataclass(frozen=True, kw_only=True)
class ToolExecutionPageAuthority:
    items: tuple[ToolExecutionAuthority, ...]
    total: int
    failed_total: int


@dataclass(frozen=True, kw_only=True)
class ConversationSessionAuthoritySnapshot:
    conversation: ConversationAuthority
    attempts: tuple[WorkspaceAttemptAuthority, ...]
    conversation_tasks: tuple[ConversationTaskAuthority, ...]
    workspace_plan_context: WorkspacePlanContextAuthority | None
    pending_hitl: tuple[PendingHITLAuthority, ...]
    has_blocking_hitl: bool
    artifact_records: tuple[ArtifactRecordAuthority, ...]
    tool_executions: ToolExecutionPageAuthority


class ConversationSessionProjectionReader(Protocol):
    async def load(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        workspace_id: str | None,
        user_id: str,
        now: datetime,
        tool_limit: int,
    ) -> ConversationSessionAuthoritySnapshot | None: ...


class ConversationSessionProjectionService:
    """Compose one scoped projection without inventing desktop runtime records."""

    TOOL_RECORD_LIMIT = 200

    def __init__(self, reader: ConversationSessionProjectionReader) -> None:
        super().__init__()
        self._reader = reader

    async def get_projection(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        workspace_id: str | None,
        user_id: str,
        now: datetime | None = None,
    ) -> ConversationSessionProjectionResponse:
        snapshot = await self._reader.load(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
            now=now or datetime.now(UTC),
            tool_limit=self.TOOL_RECORD_LIMIT,
        )
        if snapshot is None:
            raise ConversationSessionNotFoundError

        attempts = [self._attempt(item) for item in snapshot.attempts]
        current_attempt = attempts[0] if attempts else None
        can_send_message = not snapshot.has_blocking_hitl
        allowed_actions: list[Literal["send_message", "respond_to_hitl"]] = []
        if can_send_message:
            allowed_actions.append("send_message")
        if snapshot.pending_hitl:
            allowed_actions.append("respond_to_hitl")

        projection = ConversationSessionProjectionResponse(
            authority_kind="workspace_attempt" if current_attempt else "conversation_record",
            authority_id=current_attempt.id if current_attempt else snapshot.conversation.id,
            conversation=self._conversation(snapshot.conversation),
            execution=SessionExecutionResponse(
                current_attempt=current_attempt,
                attempt_history=attempts,
            ),
            conversation_tasks=[self._task(item) for item in snapshot.conversation_tasks],
            workspace_plan_context=self._plan(snapshot.workspace_plan_context),
            pending_hitl=[self._hitl(item) for item in snapshot.pending_hitl],
            artifact_records=[
                SessionArtifactRecordResponse(id=item.id) for item in snapshot.artifact_records
            ],
            tool_execution_records=SessionToolExecutionPageResponse(
                items=[self._tool(item) for item in snapshot.tool_executions.items],
                total=snapshot.tool_executions.total,
                truncated=snapshot.tool_executions.total > len(snapshot.tool_executions.items),
            ),
            evidence_summary=SessionEvidenceSummaryResponse(
                candidate_artifact_ref_count=sum(
                    len(item.candidate_artifact_refs) for item in snapshot.attempts
                ),
                candidate_verification_ref_count=sum(
                    len(item.candidate_verification_refs) for item in snapshot.attempts
                ),
                artifact_record_count=len(snapshot.artifact_records),
                tool_execution_record_count=snapshot.tool_executions.total,
                failed_tool_execution_count=snapshot.tool_executions.failed_total,
            ),
            capabilities=SessionCapabilitiesResponse(
                can_send_message=can_send_message,
                can_respond_to_hitl=bool(snapshot.pending_hitl),
                can_approve_plan=False,
                can_control_execution=False,
                can_review_artifacts=False,
                can_deliver_artifacts=False,
                allowed_actions=allowed_actions,
            ),
            snapshot_revision="pending",
            updated_at=self._updated_at(snapshot),
        )
        unsigned = projection.model_dump(mode="json", exclude={"snapshot_revision"})
        canonical = json.dumps(unsigned, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        revision = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        return projection.model_copy(update={"snapshot_revision": revision})

    @staticmethod
    def _conversation(source: ConversationAuthority) -> SessionConversationResponse:
        return SessionConversationResponse(
            id=source.id,
            tenant_id=source.tenant_id,
            project_id=source.project_id,
            workspace_id=source.workspace_id,
            linked_workspace_task_id=source.linked_workspace_task_id,
            workspace_name=source.workspace_name,
            user_id=source.user_id,
            title=source.title,
            summary=source.summary,
            status=source.status,
            current_mode=source.current_mode,
            conversation_mode=source.conversation_mode,
            capability_mode=source.capability_mode,
            message_count=source.message_count,
            participant_agents=list(source.participant_agents),
            coordinator_agent_id=source.coordinator_agent_id,
            focused_agent_id=source.focused_agent_id,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )

    @staticmethod
    def _attempt(source: WorkspaceAttemptAuthority) -> SessionWorkspaceAttemptResponse:
        return SessionWorkspaceAttemptResponse(
            id=source.id,
            workspace_task_id=source.workspace_task_id,
            root_goal_task_id=source.root_goal_task_id,
            workspace_id=source.workspace_id,
            conversation_id=source.conversation_id,
            attempt_number=source.attempt_number,
            status=source.status,
            worker_agent_id=source.worker_agent_id,
            leader_agent_id=source.leader_agent_id,
            candidate_summary=source.candidate_summary,
            candidate_artifact_refs=list(source.candidate_artifact_refs),
            candidate_verification_refs=list(source.candidate_verification_refs),
            leader_feedback=source.leader_feedback,
            adjudication_reason=source.adjudication_reason,
            created_at=source.created_at,
            updated_at=source.updated_at,
            completed_at=source.completed_at,
        )

    @staticmethod
    def _task(source: ConversationTaskAuthority) -> SessionConversationTaskResponse:
        return SessionConversationTaskResponse(
            id=source.id,
            conversation_id=source.conversation_id,
            content=source.content,
            status=source.status,
            priority=source.priority,
            order_index=source.order_index,
            created_at=source.created_at,
            updated_at=source.updated_at,
        )

    @classmethod
    def _plan(
        cls, source: WorkspacePlanContextAuthority | None
    ) -> SessionWorkspacePlanContextResponse | None:
        if source is None:
            return None
        return SessionWorkspacePlanContextResponse(
            id=source.id,
            workspace_id=source.workspace_id,
            goal_id=source.goal_id,
            status=source.status,
            created_at=source.created_at,
            updated_at=source.updated_at,
            linked_nodes=[cls._plan_node(item) for item in source.linked_nodes],
        )

    @staticmethod
    def _plan_node(source: WorkspacePlanNodeAuthority) -> SessionWorkspacePlanNodeResponse:
        return SessionWorkspacePlanNodeResponse(
            id=source.id,
            plan_id=source.plan_id,
            workspace_task_id=source.workspace_task_id,
            kind=source.kind,
            title=source.title,
            description=source.description,
            intent=source.intent,
            execution=source.execution,
            progress=source.progress,
            assignee_agent_id=source.assignee_agent_id,
            current_attempt_id=source.current_attempt_id,
            created_at=source.created_at,
            updated_at=source.updated_at,
            completed_at=source.completed_at,
        )

    @staticmethod
    def _hitl(source: PendingHITLAuthority) -> SessionPendingHITLResponse:
        return SessionPendingHITLResponse(
            id=source.id,
            conversation_id=source.conversation_id,
            message_id=source.message_id,
            request_type=source.request_type,
            question=source.question,
            options=list(source.options),
            context=source.context,
            metadata=source.metadata,
            status="pending",
            created_at=source.created_at,
            expires_at=source.expires_at,
        )

    @staticmethod
    def _tool(source: ToolExecutionAuthority) -> SessionToolExecutionResponse:
        return SessionToolExecutionResponse(
            id=source.id,
            message_id=source.message_id,
            call_id=source.call_id,
            tool_name=source.tool_name,
            status=source.status,
            error=source.error,
            step_number=source.step_number,
            sequence_number=source.sequence_number,
            started_at=source.started_at,
            completed_at=source.completed_at,
            duration_ms=source.duration_ms,
        )

    @classmethod
    def _updated_at(cls, snapshot: ConversationSessionAuthoritySnapshot) -> datetime:
        conversation = snapshot.conversation
        candidates = [conversation.updated_at or conversation.created_at]
        for attempt in snapshot.attempts:
            candidates.append(attempt.completed_at or attempt.updated_at or attempt.created_at)
        for task in snapshot.conversation_tasks:
            candidates.append(task.updated_at or task.created_at)
        if snapshot.workspace_plan_context is not None:
            plan = snapshot.workspace_plan_context
            candidates.append(plan.updated_at or plan.created_at)
            for node in plan.linked_nodes:
                candidates.append(node.completed_at or node.updated_at or node.created_at)
        candidates.extend(item.created_at for item in snapshot.pending_hitl)
        candidates.extend(item.created_at for item in snapshot.artifact_records)
        for tool in snapshot.tool_executions.items:
            candidates.append(tool.completed_at or tool.started_at)
        return max(cls._aware(item) for item in candidates)

    @staticmethod
    def _aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


__all__ = [
    "ArtifactRecordAuthority",
    "ConversationAuthority",
    "ConversationSessionAuthoritySnapshot",
    "ConversationSessionNotFoundError",
    "ConversationSessionProjectionService",
    "ConversationTaskAuthority",
    "PendingHITLAuthority",
    "ToolExecutionAuthority",
    "ToolExecutionPageAuthority",
    "WorkspaceAttemptAuthority",
    "WorkspacePlanContextAuthority",
    "WorkspacePlanNodeAuthority",
]
