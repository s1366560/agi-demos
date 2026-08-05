"""Compose a project My Work queue from persisted execution authorities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from src.application.schemas.agent_run_authority import RunSummaryResponse
from src.application.schemas.project_my_work import (
    MyWorkCapabilityMode,
    MyWorkGroup,
    MyWorkPermissionProfile,
    MyWorkRequiredAction,
    MyWorkStatus,
    ProjectMyWorkResponse,
    ProjectWorkItem,
)


class ProjectMyWorkAccessDeniedError(Exception):
    """Raised when the caller lacks the complete project membership scope."""


@dataclass(frozen=True, kw_only=True)
class WorkspaceAttemptAuthority:
    id: str
    conversation_id: str
    workspace_id: str
    project_id: str
    title: str
    status: str
    attempt_number: int
    conversation_agent_config: dict[str, Any] | None
    workspace_metadata: dict[str, Any] | None
    created_at: datetime
    updated_at: datetime | None
    workspace_name: str | None = None
    plan_tasks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, kw_only=True)
class HITLRequestAuthority:
    id: str
    request_type: str
    conversation_id: str
    workspace_id: str
    project_id: str
    title: str
    conversation_agent_config: dict[str, Any] | None
    request_metadata: dict[str, Any] | None
    workspace_metadata: dict[str, Any] | None
    created_at: datetime
    expires_at: datetime
    workspace_name: str | None = None
    plan_tasks: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, kw_only=True)
class AgentRunAuthority:
    id: str
    tenant_id: str
    conversation_id: str
    workspace_id: str | None
    project_id: str
    title: str
    status: str
    revision: int
    permission_profile: MyWorkPermissionProfile
    environment: str | None
    error: str | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    workspace_name: str | None
    capability_mode: MyWorkCapabilityMode | None
    summary_state: Literal["recorded", "partial"]
    summary_reason_code: str | None
    summary_status: str | None
    summary_revision: int | None
    summary_started_at: datetime | None
    summary_completed_at: datetime | None
    model_breakdown: tuple[dict[str, Any], ...]
    completion_summary: str | None
    duration_ms: int | None
    input_tokens: int | None
    output_tokens: int | None
    cost_usd: float | None
    artifact_count: int | None
    checks_passed: int | None
    checks_failed: int | None
    files_changed: int | None
    lines_added: int | None
    lines_deleted: int | None
    evidence_references: tuple[dict[str, Any], ...]


class ProjectMyWorkReader(Protocol):
    async def has_project_access(self, *, project_id: str, user_id: str) -> bool: ...

    async def list_latest_workspace_attempts(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> list[WorkspaceAttemptAuthority]: ...

    async def list_pending_hitl_requests(
        self,
        *,
        project_id: str,
        user_id: str,
        now: datetime,
    ) -> list[HITLRequestAuthority]: ...

    async def list_agent_runs(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> list[AgentRunAuthority]: ...


class ProjectMyWorkService:
    """Build the queue without inferring authority state from messages or events."""

    _RUNNING_ATTEMPT_STATUSES = frozenset({"pending", "running", "awaiting_leader_adjudication"})
    _HIDDEN_ATTEMPT_STATUSES = frozenset({"accepted", "rejected", "cancelled"})
    _INPUT_HITL_TYPES = frozenset({"clarification", "decision", "env_var", "a2ui_action"})

    def __init__(self, reader: ProjectMyWorkReader) -> None:
        super().__init__()
        self._reader = reader

    async def list_for_project(
        self,
        *,
        project_id: str,
        user_id: str,
        now: datetime | None = None,
    ) -> ProjectMyWorkResponse:
        if not await self._reader.has_project_access(project_id=project_id, user_id=user_id):
            raise ProjectMyWorkAccessDeniedError

        observed_at = now or datetime.now(UTC)
        attempts = await self._reader.list_latest_workspace_attempts(
            project_id=project_id,
            user_id=user_id,
        )
        hitl_requests = await self._reader.list_pending_hitl_requests(
            project_id=project_id,
            user_id=user_id,
            now=observed_at,
        )
        runs = await self._reader.list_agent_runs(
            project_id=project_id,
            user_id=user_id,
        )

        active_hitl_items = [
            (request, item)
            for request in hitl_requests
            if self._is_active_hitl(request, observed_at)
            if (item := self._hitl_item(request)) is not None
        ]
        hitl_conversation_ids = {request.conversation_id for request, _ in active_hitl_items}
        run_items = [
            (run, item)
            for run in runs
            if run.conversation_id not in hitl_conversation_ids
            if (item := self._run_item(run)) is not None
        ]
        run_conversation_ids = {run.conversation_id for run, _ in run_items}

        items = [
            item
            for attempt in attempts
            if attempt.conversation_id not in hitl_conversation_ids
            if attempt.conversation_id not in run_conversation_ids
            if (item := self._attempt_item(attempt)) is not None
        ]
        items.extend(item for _, item in run_items)
        items.extend(item for _, item in active_hitl_items)
        items.sort(key=lambda item: (item.updated_at, item.authority_id), reverse=True)
        return ProjectMyWorkResponse(project_id=project_id, items=items, total=len(items))

    @staticmethod
    def _run_item(source: AgentRunAuthority) -> ProjectWorkItem | None:
        if source.status in {"queued", "running"}:
            group: MyWorkGroup = "running"
            status: MyWorkStatus = "running"
            required_action: MyWorkRequiredAction = "observe"
        elif source.status == "ready_review":
            group = "ready_review"
            status = "ready_review"
            required_action = "review_approval"
        elif source.status in {"failed", "cancelled"}:
            group = "ready_review"
            status = "failed"
            required_action = "inspect_failure"
        else:
            return None
        return ProjectWorkItem(
            id=f"agent_run:{source.id}",
            authority_kind="agent_run",
            authority_id=source.id,
            run_id=source.id,
            conversation_id=source.conversation_id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            title=source.title,
            capability_mode=source.capability_mode,
            group=group,
            status=status,
            required_action=required_action,
            revision=source.revision,
            permission_profile=source.permission_profile,
            environment=source.environment,
            error=source.error,
            created_at=source.created_at,
            updated_at=source.updated_at,
            workspace_name=source.workspace_name,
            summary=source.completion_summary,
            run_summary=RunSummaryResponse(
                run_id=source.id,
                tenant_id=source.tenant_id,
                project_id=source.project_id,
                conversation_id=source.conversation_id,
                status=source.summary_status or source.status,
                revision=source.summary_revision or source.revision,
                summary_state=source.summary_state,
                reason_code=source.summary_reason_code,
                started_at=source.summary_started_at,
                completed_at=source.summary_completed_at,
                duration_ms=source.duration_ms,
                input_tokens=source.input_tokens,
                output_tokens=source.output_tokens,
                cost_usd=source.cost_usd,
                model_breakdown=list(source.model_breakdown),
                completion_summary=source.completion_summary,
                artifact_count=source.artifact_count,
                checks_passed=source.checks_passed,
                checks_failed=source.checks_failed,
                files_changed=source.files_changed,
                lines_added=source.lines_added,
                lines_deleted=source.lines_deleted,
                evidence_references=list(source.evidence_references),
            ),
        )

    @classmethod
    def _attempt_item(cls, source: WorkspaceAttemptAuthority) -> ProjectWorkItem | None:
        if source.status in cls._HIDDEN_ATTEMPT_STATUSES:
            return None
        group: MyWorkGroup
        status: MyWorkStatus
        required_action: MyWorkRequiredAction
        if source.status in cls._RUNNING_ATTEMPT_STATUSES:
            group = "running"
            status = "running"
            required_action = "observe"
        elif source.status == "blocked":
            group = "needs_input"
            status = "failed"
            required_action = "inspect_failure"
        else:
            return None

        updated_at = source.updated_at or source.created_at
        summary, phase, progress = cls._plan_projection(source.plan_tasks)
        return ProjectWorkItem(
            id=f"workspace_attempt:{source.id}",
            authority_kind="workspace_attempt",
            authority_id=source.id,
            run_id=None,
            conversation_id=source.conversation_id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            title=source.title,
            capability_mode=cls._capability_mode(
                source.conversation_agent_config,
                source.workspace_metadata,
            ),
            group=group,
            status=status,
            required_action=required_action,
            revision=None,
            permission_profile=None,
            environment=None,
            error=None,
            attempt_number=source.attempt_number,
            created_at=source.created_at,
            updated_at=updated_at,
            last_heartbeat_at=None,
            workspace_name=source.workspace_name,
            summary=summary,
            phase=phase,
            progress=progress,
        )

    @classmethod
    def _hitl_item(cls, source: HITLRequestAuthority) -> ProjectWorkItem | None:
        request_type = cls._trusted_hitl_type(source)
        group: MyWorkGroup
        status: MyWorkStatus
        required_action: MyWorkRequiredAction
        if request_type == "permission":
            group = "needs_approval"
            status = "needs_approval"
            required_action = "review_approval"
        elif request_type in cls._INPUT_HITL_TYPES:
            group = "needs_input"
            status = "needs_input"
            required_action = "provide_input"
        else:
            return None

        summary, phase, progress = cls._plan_projection(source.plan_tasks)
        return ProjectWorkItem(
            id=f"hitl_request:{source.id}",
            authority_kind="hitl_request",
            authority_id=source.id,
            run_id=None,
            conversation_id=source.conversation_id,
            workspace_id=source.workspace_id,
            project_id=source.project_id,
            title=source.title,
            capability_mode=cls._capability_mode(
                source.conversation_agent_config,
                source.workspace_metadata,
            ),
            group=group,
            status=status,
            required_action=required_action,
            revision=None,
            permission_profile=None,
            environment=None,
            error=None,
            attempt_number=None,
            created_at=source.created_at,
            updated_at=source.created_at,
            last_heartbeat_at=None,
            workspace_name=source.workspace_name,
            summary=summary,
            phase=phase,
            progress=progress,
        )

    @staticmethod
    def _plan_projection(
        tasks: tuple[dict[str, Any], ...],
    ) -> tuple[str | None, str | None, int | None]:
        if not tasks:
            return None, None, None
        completed = sum(task.get("status") == "completed" for task in tasks)
        current = next(
            (task for task in tasks if task.get("status") == "in_progress"),
            None,
        ) or next((task for task in tasks if task.get("status") == "pending"), tasks[-1])

        def text(field: str) -> str | None:
            value = current.get(field)
            return value.strip() if isinstance(value, str) and value.strip() else None

        phase = text("title") or text("content")
        summary = text("result_summary") or text("description") or phase
        return summary, phase, completed * 100 // len(tasks)

    @staticmethod
    def _capability_mode(*structured_values: dict[str, Any] | None) -> MyWorkCapabilityMode | None:
        for value in structured_values:
            candidate = value.get("capability_mode") if isinstance(value, dict) else None
            if candidate == "work":
                return "work"
            if candidate == "code":
                return "code"
        return None

    @classmethod
    def _trusted_hitl_type(cls, source: HITLRequestAuthority) -> str:
        metadata_type = (
            source.request_metadata.get("hitl_type")
            if isinstance(source.request_metadata, dict)
            else None
        )
        supported_types = cls._INPUT_HITL_TYPES | {"permission"}
        if isinstance(metadata_type, str) and metadata_type in supported_types:
            return metadata_type
        return source.request_type

    @staticmethod
    def _is_active_hitl(source: HITLRequestAuthority, now: datetime) -> bool:
        expires_at = source.expires_at
        if expires_at.tzinfo is None and now.tzinfo is not None:
            expires_at = expires_at.replace(tzinfo=UTC)
        elif expires_at.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return expires_at > now
