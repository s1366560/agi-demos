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
from src.domain.ports.services.workspace_authority_port import WorkspaceAuthorityPort
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
)


class SqlProjectMyWorkReader:
    """Read platform authorities and resolve Workspace metadata through Avernet Core."""

    def __init__(
        self,
        db: AsyncSession,
        workspace_authority: WorkspaceAuthorityPort,
        *,
        is_superuser: bool = False,
    ) -> None:
        super().__init__()
        self._db = db
        self._workspace_authority = workspace_authority
        self._is_superuser = is_superuser

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
        """Legacy SQL attempt projections are no longer a Workspace authority."""
        return []

    async def list_pending_hitl_requests(
        self,
        *,
        project_id: str,
        user_id: str,
        now: datetime,
    ) -> list[HITLRequestAuthority]:
        conversation = Conversation
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
                HITLRequest.tenant_id,
                conversation.title,
                conversation.agent_config.label("conversation_agent_config"),
                HITLRequest.request_metadata,
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
                Project,
                and_(
                    Project.id == conversation.project_id,
                    Project.tenant_id == conversation.tenant_id,
                ),
            )
            .where(
                Project.id == project_id,
                conversation.workspace_id.is_not(None),
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
            )
            .order_by(HITLRequest.created_at.desc(), HITLRequest.id.desc())
        )
        result = await self._db.execute(refresh_select_statement(statement))
        rows = result.all()
        profiles = await self._workspace_authority.resolve_profiles(
            workspace_ids={str(row.workspace_id) for row in rows if row.workspace_id},
            user_id=user_id,
            is_superuser=self._is_superuser,
        )
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
                workspace_metadata=profiles[row.workspace_id].metadata,
                created_at=row.created_at,
                expires_at=row.expires_at,
                workspace_name=profiles[row.workspace_id].name,
                plan_tasks=self._json_task_list(row.plan_tasks),
            )
            for row in rows
            if row.workspace_id in profiles
            and profiles[row.workspace_id].tenant_id == row.tenant_id
            and profiles[row.workspace_id].project_id == row.project_id
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
        summary = AgentRunSummaryModel
        statement = (
            select(
                ranked_runs,
                conversation.title,
                conversation.agent_config,
                conversation.tenant_id,
                conversation.workspace_id,
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
            .join(
                Project,
                and_(
                    Project.id == conversation.project_id,
                    Project.tenant_id == conversation.tenant_id,
                ),
            )
            .outerjoin(summary, summary.run_id == ranked_runs.c.run_id)
            .where(
                ranked_runs.c.authority_rank == 1,
                ranked_runs.c.project_id == project_id,
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
        )
        result = await self._db.execute(refresh_select_statement(statement))
        rows = result.all()
        profiles = await self._workspace_authority.resolve_profiles(
            workspace_ids={str(row.workspace_id) for row in rows if row.workspace_id},
            user_id=user_id,
            is_superuser=self._is_superuser,
        )
        authorities: list[AgentRunAuthority] = []
        for row in rows:
            profile = profiles.get(row.workspace_id) if row.workspace_id else None
            if row.workspace_id and (
                profile is None
                or profile.tenant_id != row.tenant_id
                or profile.project_id != row.project_id
            ):
                continue
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
                    workspace_name=profile.name if profile else None,
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
