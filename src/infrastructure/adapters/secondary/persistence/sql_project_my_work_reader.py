"""SQL read adapter for the project My Work projection."""

from __future__ import annotations

from datetime import datetime
from typing import Any, cast

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.schemas.project_my_work import (
    MyWorkCapabilityMode,
    MyWorkPermissionProfile,
)
from src.application.services.project_my_work_service import (
    AgentRunAuthority,
    HITLRequestAuthority,
    WorkspaceAttemptAuthority,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanRunModel,
    AgentPlanVersionModel,
    AgentRunSummaryModel,
    Conversation,
    HITLRequest,
    Project,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)


class SqlProjectMyWorkReader:
    """Read only authorities within the caller's complete resource scope."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self._db = db

    async def has_project_access(self, *, project_id: str, user_id: str) -> bool:
        statement = (
            select(Project.id)
            .where(
                Project.id == project_id,
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == user_id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Project.tenant_id,
                        UserTenant.user_id == user_id,
                    )
                ),
            )
            .limit(1)
        )
        result = await self._db.execute(refresh_select_statement(statement))
        return result.scalar_one_or_none() is not None

    async def list_latest_workspace_attempts(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> list[WorkspaceAttemptAuthority]:
        attempt = WorkspaceTaskSessionAttemptModel
        task = WorkspaceTaskModel
        workspace = WorkspaceModel
        conversation = Conversation
        latest_plan_tasks = (
            select(AgentPlanVersionModel.tasks_json)
            .where(AgentPlanVersionModel.conversation_id == conversation.id)
            .order_by(AgentPlanVersionModel.version.desc())
            .limit(1)
            .scalar_subquery()
        )

        ranked_attempts = select(
            attempt.id.label("authority_id"),
            attempt.workspace_task_id,
            attempt.conversation_id,
            attempt.workspace_id,
            attempt.status,
            attempt.attempt_number,
            attempt.created_at,
            attempt.updated_at,
            func.row_number()
            .over(
                partition_by=attempt.workspace_task_id,
                order_by=(
                    attempt.attempt_number.desc(),
                    attempt.created_at.desc(),
                    attempt.id.asc(),
                ),
            )
            .label("authority_rank"),
        ).subquery()
        statement = (
            select(
                ranked_attempts.c.authority_id,
                ranked_attempts.c.conversation_id,
                ranked_attempts.c.workspace_id,
                workspace.project_id,
                task.title,
                ranked_attempts.c.status,
                ranked_attempts.c.attempt_number,
                conversation.agent_config.label("conversation_agent_config"),
                workspace.metadata_json.label("workspace_metadata"),
                workspace.name.label("workspace_name"),
                latest_plan_tasks.label("plan_tasks"),
                ranked_attempts.c.created_at,
                ranked_attempts.c.updated_at,
            )
            .select_from(ranked_attempts)
            .join(
                task,
                and_(
                    task.id == ranked_attempts.c.workspace_task_id,
                    task.workspace_id == ranked_attempts.c.workspace_id,
                ),
            )
            .join(workspace, workspace.id == ranked_attempts.c.workspace_id)
            .join(
                conversation,
                and_(
                    conversation.id == ranked_attempts.c.conversation_id,
                    conversation.project_id == workspace.project_id,
                    conversation.tenant_id == workspace.tenant_id,
                    conversation.workspace_id == workspace.id,
                    conversation.linked_workspace_task_id == task.id,
                    conversation.user_id == user_id,
                ),
            )
            .join(
                Project,
                and_(
                    Project.id == workspace.project_id,
                    Project.tenant_id == workspace.tenant_id,
                ),
            )
            .where(
                ranked_attempts.c.authority_rank == 1,
                Project.id == project_id,
                workspace.is_archived.is_(False),
                task.archived_at.is_(None),
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == user_id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Project.tenant_id,
                        UserTenant.user_id == user_id,
                    )
                ),
                exists(
                    select(WorkspaceMemberModel.id).where(
                        WorkspaceMemberModel.workspace_id == workspace.id,
                        WorkspaceMemberModel.user_id == user_id,
                    )
                ),
            )
        )
        result = await self._db.execute(refresh_select_statement(statement))
        return [
            WorkspaceAttemptAuthority(
                id=row.authority_id,
                conversation_id=row.conversation_id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                title=row.title,
                status=row.status,
                attempt_number=row.attempt_number,
                conversation_agent_config=self._json_object(row.conversation_agent_config),
                workspace_metadata=self._json_object(row.workspace_metadata),
                created_at=row.created_at,
                updated_at=row.updated_at,
                workspace_name=row.workspace_name,
                plan_tasks=self._json_task_list(row.plan_tasks),
            )
            for row in result.all()
        ]

    async def list_pending_hitl_requests(
        self,
        *,
        project_id: str,
        user_id: str,
        now: datetime,
    ) -> list[HITLRequestAuthority]:
        conversation = Conversation
        workspace = WorkspaceModel
        latest_plan_tasks = (
            select(AgentPlanVersionModel.tasks_json)
            .where(AgentPlanVersionModel.conversation_id == conversation.id)
            .order_by(AgentPlanVersionModel.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(
                HITLRequest.id.label("authority_id"),
                HITLRequest.request_type,
                HITLRequest.conversation_id,
                conversation.workspace_id,
                HITLRequest.project_id,
                conversation.title,
                conversation.agent_config.label("conversation_agent_config"),
                HITLRequest.request_metadata,
                workspace.metadata_json.label("workspace_metadata"),
                workspace.name.label("workspace_name"),
                latest_plan_tasks.label("plan_tasks"),
                HITLRequest.created_at,
                HITLRequest.expires_at,
            )
            .select_from(HITLRequest)
            .join(
                conversation,
                and_(
                    conversation.id == HITLRequest.conversation_id,
                    conversation.project_id == HITLRequest.project_id,
                    conversation.tenant_id == HITLRequest.tenant_id,
                    conversation.user_id == user_id,
                ),
            )
            .join(
                workspace,
                and_(
                    workspace.id == conversation.workspace_id,
                    workspace.project_id == conversation.project_id,
                    workspace.tenant_id == conversation.tenant_id,
                ),
            )
            .join(
                Project,
                and_(
                    Project.id == workspace.project_id,
                    Project.tenant_id == workspace.tenant_id,
                ),
            )
            .where(
                Project.id == project_id,
                workspace.is_archived.is_(False),
                HITLRequest.status == "pending",
                HITLRequest.expires_at > now,
                or_(HITLRequest.user_id.is_(None), HITLRequest.user_id == user_id),
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == Project.id,
                        UserProject.user_id == user_id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == Project.tenant_id,
                        UserTenant.user_id == user_id,
                    )
                ),
                exists(
                    select(WorkspaceMemberModel.id).where(
                        WorkspaceMemberModel.workspace_id == workspace.id,
                        WorkspaceMemberModel.user_id == user_id,
                    )
                ),
            )
            .order_by(HITLRequest.created_at.desc(), HITLRequest.id.desc())
        )
        result = await self._db.execute(refresh_select_statement(statement))
        return [
            HITLRequestAuthority(
                id=row.authority_id,
                request_type=row.request_type,
                conversation_id=row.conversation_id,
                workspace_id=row.workspace_id,
                project_id=row.project_id,
                title=row.title,
                conversation_agent_config=self._json_object(row.conversation_agent_config),
                request_metadata=self._json_object(row.request_metadata),
                workspace_metadata=self._json_object(row.workspace_metadata),
                created_at=row.created_at,
                expires_at=row.expires_at,
                workspace_name=row.workspace_name,
                plan_tasks=self._json_task_list(row.plan_tasks),
            )
            for row in result.all()
        ]

    async def list_agent_runs(
        self,
        *,
        project_id: str,
        user_id: str,
    ) -> list[AgentRunAuthority]:
        """Return the latest visible run per conversation with its persisted summary."""

        run = AgentPlanRunModel
        ranked_runs = (
            select(
                run.id.label("run_id"),
                run.conversation_id,
                run.project_id,
                run.status,
                run.revision,
                run.permission_profile,
                run.authorization_snapshot,
                run.error,
                run.created_at,
                run.updated_at,
                run.completed_at,
                func.row_number()
                .over(
                    partition_by=run.conversation_id,
                    order_by=(run.created_at.desc(), run.id.desc()),
                )
                .label("authority_rank"),
            )
            .where(run.status.in_(["queued", "running", "ready_review", "failed", "cancelled"]))
            .subquery()
        )
        conversation = Conversation
        workspace = WorkspaceModel
        summary = AgentRunSummaryModel
        statement = (
            select(
                ranked_runs,
                conversation.title,
                conversation.agent_config,
                conversation.tenant_id,
                conversation.workspace_id,
                workspace.name.label("workspace_name"),
                summary.summary_state,
                summary.reason_code,
                summary.status.label("summary_status"),
                summary.revision.label("summary_revision"),
                summary.started_at.label("summary_started_at"),
                summary.completed_at.label("summary_completed_at"),
                summary.model_breakdown_json,
                summary.completion_summary,
                summary.duration_ms,
                summary.input_tokens,
                summary.output_tokens,
                summary.cost_usd,
                summary.artifact_count,
                summary.checks_passed,
                summary.checks_failed,
                summary.files_changed,
                summary.lines_added,
                summary.lines_deleted,
                summary.evidence_references_json,
            )
            .select_from(ranked_runs)
            .join(
                conversation,
                and_(
                    conversation.id == ranked_runs.c.conversation_id,
                    conversation.project_id == ranked_runs.c.project_id,
                    conversation.user_id == user_id,
                ),
            )
            .outerjoin(
                workspace,
                and_(
                    workspace.id == conversation.workspace_id,
                    workspace.project_id == conversation.project_id,
                    workspace.tenant_id == conversation.tenant_id,
                ),
            )
            .outerjoin(summary, summary.run_id == ranked_runs.c.run_id)
            .where(
                ranked_runs.c.authority_rank == 1,
                ranked_runs.c.project_id == project_id,
                exists(
                    select(UserProject.id).where(
                        UserProject.project_id == project_id,
                        UserProject.user_id == user_id,
                    )
                ),
                exists(
                    select(UserTenant.id).where(
                        UserTenant.tenant_id == conversation.tenant_id,
                        UserTenant.user_id == user_id,
                    )
                ),
                or_(
                    conversation.workspace_id.is_(None),
                    and_(
                        workspace.id.is_not(None),
                        workspace.is_archived.is_(False),
                        exists(
                            select(WorkspaceMemberModel.id).where(
                                WorkspaceMemberModel.workspace_id == workspace.id,
                                WorkspaceMemberModel.user_id == user_id,
                            )
                        ),
                    ),
                ),
            )
        )
        result = await self._db.execute(refresh_select_statement(statement))
        authorities: list[AgentRunAuthority] = []
        for row in result.all():
            config = self._json_object(row.agent_config) or {}
            mode = config.get("capability_mode")
            capability_mode = mode if mode in {"work", "code"} else None
            permission_profile = (
                row.permission_profile
                if row.permission_profile in {"read_only", "workspace_write", "full_access"}
                else "read_only"
            )
            authorization = self._json_object(row.authorization_snapshot) or {}
            environment_raw = authorization.get("environment")
            environment = (
                str(environment_raw.get("id"))
                if isinstance(environment_raw, dict) and environment_raw.get("id")
                else None
            )
            evidence = row.evidence_references_json
            authorities.append(
                AgentRunAuthority(
                    id=row.run_id,
                    tenant_id=row.tenant_id,
                    conversation_id=row.conversation_id,
                    workspace_id=row.workspace_id,
                    project_id=row.project_id,
                    title=row.title,
                    status=row.status,
                    revision=row.revision,
                    permission_profile=cast(MyWorkPermissionProfile, permission_profile),
                    environment=environment,
                    error=row.error,
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    completed_at=row.completed_at,
                    workspace_name=row.workspace_name,
                    capability_mode=cast(MyWorkCapabilityMode | None, capability_mode),
                    summary_state=row.summary_state or "partial",
                    summary_reason_code=row.reason_code
                    or ("summary_not_recorded" if row.summary_state is None else None),
                    summary_status=row.summary_status,
                    summary_revision=row.summary_revision,
                    summary_started_at=row.summary_started_at,
                    summary_completed_at=row.summary_completed_at,
                    model_breakdown=(
                        tuple(item for item in row.model_breakdown_json if isinstance(item, dict))
                        if isinstance(row.model_breakdown_json, list)
                        else ()
                    ),
                    completion_summary=row.completion_summary,
                    duration_ms=row.duration_ms,
                    input_tokens=row.input_tokens,
                    output_tokens=row.output_tokens,
                    cost_usd=row.cost_usd,
                    artifact_count=row.artifact_count,
                    checks_passed=row.checks_passed,
                    checks_failed=row.checks_failed,
                    files_changed=row.files_changed,
                    lines_added=row.lines_added,
                    lines_deleted=row.lines_deleted,
                    evidence_references=(
                        tuple(item for item in evidence if isinstance(item, dict))
                        if isinstance(evidence, list)
                        else ()
                    ),
                )
            )
        return authorities

    @staticmethod
    def _json_object(value: object) -> dict[str, Any] | None:
        return cast(dict[str, Any], value) if isinstance(value, dict) else None

    @staticmethod
    def _json_task_list(value: object) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        return tuple(cast(dict[str, Any], item) for item in value if isinstance(item, dict))
