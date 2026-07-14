"""SQL reader for the scoped cloud conversation session projection."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, cast

from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.conversation_session_projection_service import (
    ArtifactRecordAuthority,
    CapabilityMode,
    ConversationAuthority,
    ConversationSessionAuthoritySnapshot,
    ConversationTaskAuthority,
    HITLKind,
    PendingHITLAuthority,
    ToolExecutionAuthority,
    ToolExecutionPageAuthority,
    WorkspaceAttemptAuthority,
    WorkspacePlanContextAuthority,
    WorkspacePlanNodeAuthority,
)
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.artifact_model import ArtifactModel
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentTaskModel,
    Conversation,
    HITLRequest,
    PlanModel,
    PlanNodeModel,
    Project,
    ToolExecutionRecord,
    UserProject,
    UserTenant,
    WorkspaceMemberModel,
    WorkspaceModel,
    WorkspaceTaskModel,
    WorkspaceTaskSessionAttemptModel,
)
from src.infrastructure.agent.hitl.utils import (
    contains_secret_like_text,
    sanitize_env_var_context,
    sanitize_env_var_text,
    sanitize_hitl_scalar,
    sanitize_hitl_text,
)


class SqlConversationSessionProjectionReader:
    """Read only records that match the caller's complete resource scope."""

    _HITL_KINDS = frozenset({"clarification", "decision", "env_var", "permission", "a2ui_action"})
    _OPTION_KEYS = frozenset({"id", "label", "description", "recommended", "is_default"})

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self._db = db

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
    ) -> ConversationSessionAuthoritySnapshot | None:
        conversation = await self._load_conversation(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            project_id=project_id,
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if conversation is None:
            return None
        attempts = await self._load_attempts(conversation)
        tasks = await self._load_conversation_tasks(conversation.id)
        plan = await self._load_workspace_plan_context(conversation)
        pending_hitl, has_blocking_hitl = await self._load_pending_hitl(
            conversation=conversation,
            user_id=user_id,
            now=now,
        )
        artifact_records = await self._load_artifact_records(conversation)
        tool_executions = await self._load_tool_executions(
            conversation_id=conversation.id,
            limit=tool_limit,
        )
        return ConversationSessionAuthoritySnapshot(
            conversation=conversation,
            attempts=attempts,
            conversation_tasks=tasks,
            workspace_plan_context=plan,
            pending_hitl=pending_hitl,
            has_blocking_hitl=has_blocking_hitl,
            artifact_records=artifact_records,
            tool_executions=tool_executions,
        )

    async def _load_conversation(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        project_id: str,
        workspace_id: str | None,
        user_id: str,
    ) -> ConversationAuthority | None:
        workspace_name = (
            select(WorkspaceModel.name)
            .where(
                WorkspaceModel.id == Conversation.workspace_id,
                WorkspaceModel.tenant_id == Conversation.tenant_id,
                WorkspaceModel.project_id == Conversation.project_id,
            )
            .scalar_subquery()
        )
        conditions = [
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.project_id == project_id,
            Conversation.user_id == user_id,
            exists(
                select(Project.id).where(
                    Project.id == Conversation.project_id,
                    Project.tenant_id == Conversation.tenant_id,
                )
            ),
            exists(
                select(UserProject.id).where(
                    UserProject.project_id == Conversation.project_id,
                    UserProject.user_id == user_id,
                )
            ),
            exists(
                select(UserTenant.id).where(
                    UserTenant.tenant_id == Conversation.tenant_id,
                    UserTenant.user_id == user_id,
                )
            ),
            or_(
                Conversation.linked_workspace_task_id.is_(None),
                exists(
                    select(WorkspaceTaskModel.id).where(
                        WorkspaceTaskModel.id == Conversation.linked_workspace_task_id,
                        WorkspaceTaskModel.workspace_id == Conversation.workspace_id,
                        WorkspaceTaskModel.archived_at.is_(None),
                    )
                ),
            ),
        ]
        if workspace_id is None:
            conditions.append(Conversation.workspace_id.is_(None))
        else:
            conditions.extend(
                [
                    Conversation.workspace_id == workspace_id,
                    exists(
                        select(WorkspaceModel.id).where(
                            WorkspaceModel.id == workspace_id,
                            WorkspaceModel.tenant_id == tenant_id,
                            WorkspaceModel.project_id == project_id,
                            WorkspaceModel.is_archived.is_(False),
                        )
                    ),
                    exists(
                        select(WorkspaceMemberModel.id).where(
                            WorkspaceMemberModel.workspace_id == workspace_id,
                            WorkspaceMemberModel.user_id == user_id,
                        )
                    ),
                ]
            )
        result = await self._db.execute(
            refresh_select_statement(
                select(Conversation, workspace_name.label("workspace_name"))
                .where(*conditions)
                .limit(1)
            )
        )
        row = result.one_or_none()
        if row is None:
            return None
        record = row[0]
        return ConversationAuthority(
            id=record.id,
            tenant_id=record.tenant_id,
            project_id=record.project_id,
            workspace_id=record.workspace_id,
            linked_workspace_task_id=record.linked_workspace_task_id,
            workspace_name=row.workspace_name,
            user_id=record.user_id,
            title=record.title,
            summary=record.summary,
            status=record.status,
            current_mode=record.current_mode,
            conversation_mode=record.conversation_mode,
            capability_mode=self._capability_mode(record.agent_config),
            message_count=record.message_count,
            participant_agents=self._string_tuple(record.participant_agents),
            coordinator_agent_id=record.coordinator_agent_id,
            focused_agent_id=record.focused_agent_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    async def _load_attempts(
        self, conversation: ConversationAuthority
    ) -> tuple[WorkspaceAttemptAuthority, ...]:
        if conversation.workspace_id is None or conversation.linked_workspace_task_id is None:
            return ()
        attempt = WorkspaceTaskSessionAttemptModel
        result = await self._db.execute(
            refresh_select_statement(
                select(attempt)
                .where(
                    attempt.conversation_id == conversation.id,
                    attempt.workspace_id == conversation.workspace_id,
                    attempt.workspace_task_id == conversation.linked_workspace_task_id,
                )
                .order_by(
                    attempt.attempt_number.desc(),
                    attempt.created_at.desc(),
                    attempt.id.desc(),
                )
            )
        )
        return tuple(
            WorkspaceAttemptAuthority(
                id=item.id,
                workspace_task_id=item.workspace_task_id,
                root_goal_task_id=item.root_goal_task_id,
                workspace_id=item.workspace_id,
                conversation_id=cast(str, item.conversation_id),
                attempt_number=item.attempt_number,
                status=item.status,
                worker_agent_id=item.worker_agent_id,
                leader_agent_id=item.leader_agent_id,
                candidate_summary=item.candidate_summary,
                candidate_artifact_refs=self._string_tuple(item.candidate_artifacts_json),
                candidate_verification_refs=self._string_tuple(item.candidate_verifications_json),
                leader_feedback=item.leader_feedback,
                adjudication_reason=item.adjudication_reason,
                created_at=item.created_at,
                updated_at=item.updated_at,
                completed_at=item.completed_at,
            )
            for item in result.scalars().all()
        )

    async def _load_conversation_tasks(
        self, conversation_id: str
    ) -> tuple[ConversationTaskAuthority, ...]:
        result = await self._db.execute(
            refresh_select_statement(
                select(AgentTaskModel)
                .where(AgentTaskModel.conversation_id == conversation_id)
                .order_by(
                    AgentTaskModel.order_index.asc(),
                    AgentTaskModel.created_at.asc(),
                    AgentTaskModel.id.asc(),
                )
            )
        )
        return tuple(
            ConversationTaskAuthority(
                id=item.id,
                conversation_id=item.conversation_id,
                content=item.content,
                status=item.status,
                priority=item.priority,
                order_index=item.order_index,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in result.scalars().all()
        )

    async def _load_workspace_plan_context(
        self, conversation: ConversationAuthority
    ) -> WorkspacePlanContextAuthority | None:
        if conversation.workspace_id is None or conversation.linked_workspace_task_id is None:
            return None
        plan_result = await self._db.execute(
            refresh_select_statement(
                select(PlanModel)
                .where(
                    PlanModel.workspace_id == conversation.workspace_id,
                    exists(
                        select(PlanNodeModel.id).where(
                            PlanNodeModel.plan_id == PlanModel.id,
                            PlanNodeModel.workspace_task_id
                            == conversation.linked_workspace_task_id,
                        )
                    ),
                )
                .order_by(PlanModel.created_at.desc(), PlanModel.id.desc())
                .limit(1)
            )
        )
        plan = plan_result.scalar_one_or_none()
        if plan is None:
            return None
        node_result = await self._db.execute(
            refresh_select_statement(
                select(PlanNodeModel)
                .where(
                    PlanNodeModel.plan_id == plan.id,
                    PlanNodeModel.workspace_task_id == conversation.linked_workspace_task_id,
                )
                .order_by(PlanNodeModel.created_at.asc(), PlanNodeModel.id.asc())
            )
        )
        nodes = tuple(self._plan_node(item) for item in node_result.scalars().all())
        return WorkspacePlanContextAuthority(
            id=plan.id,
            workspace_id=plan.workspace_id,
            goal_id=plan.goal_id,
            status=plan.status,
            created_at=plan.created_at,
            updated_at=plan.updated_at,
            linked_nodes=nodes,
        )

    async def _load_pending_hitl(
        self,
        *,
        conversation: ConversationAuthority,
        user_id: str,
        now: datetime,
    ) -> tuple[tuple[PendingHITLAuthority, ...], bool]:
        result = await self._db.execute(
            refresh_select_statement(
                select(
                    HITLRequest.id,
                    HITLRequest.request_type,
                    HITLRequest.conversation_id,
                    HITLRequest.message_id,
                    HITLRequest.user_id,
                    HITLRequest.question,
                    HITLRequest.options,
                    HITLRequest.context,
                    HITLRequest.request_metadata,
                    HITLRequest.created_at,
                    HITLRequest.expires_at,
                )
                .where(
                    HITLRequest.conversation_id == conversation.id,
                    HITLRequest.tenant_id == conversation.tenant_id,
                    HITLRequest.project_id == conversation.project_id,
                    HITLRequest.status == "pending",
                    HITLRequest.expires_at > now,
                )
                .order_by(HITLRequest.created_at.desc(), HITLRequest.id.desc())
            )
        )
        records = result.all()
        items: list[PendingHITLAuthority] = []
        for record in records:
            if record.user_id is not None and record.user_id != user_id:
                continue
            kind = self._hitl_kind(record.request_type, record.request_metadata)
            if kind is None:
                continue
            prompt = (
                sanitize_env_var_text(record.question)
                if kind == "env_var"
                else sanitize_hitl_text(record.question)
            )
            if prompt is None:
                continue
            context = sanitize_env_var_context(record.context) if kind == "env_var" else {}
            items.append(
                PendingHITLAuthority(
                    id=record.id,
                    conversation_id=record.conversation_id,
                    message_id=record.message_id,
                    request_type=kind,
                    question=prompt,
                    options=self._safe_options(record.options),
                    context=context,
                    metadata={"hitl_type": kind},
                    created_at=record.created_at,
                    expires_at=record.expires_at,
                )
            )
        return tuple(items), bool(records)

    async def _load_artifact_records(
        self, conversation: ConversationAuthority
    ) -> tuple[ArtifactRecordAuthority, ...]:
        workspace_condition = (
            ArtifactModel.workspace_id.is_(None)
            if conversation.workspace_id is None
            else ArtifactModel.workspace_id == conversation.workspace_id
        )
        result = await self._db.execute(
            refresh_select_statement(
                select(ArtifactModel.id, ArtifactModel.created_at)
                .where(
                    ArtifactModel.conversation_id == conversation.id,
                    ArtifactModel.tenant_id == conversation.tenant_id,
                    ArtifactModel.project_id == conversation.project_id,
                    workspace_condition,
                )
                .order_by(ArtifactModel.created_at.asc(), ArtifactModel.id.asc())
            )
        )
        return tuple(
            ArtifactRecordAuthority(id=row.id, created_at=row.created_at) for row in result.all()
        )

    async def _load_tool_executions(
        self, *, conversation_id: str, limit: int
    ) -> ToolExecutionPageAuthority:
        result = await self._db.execute(
            refresh_select_statement(
                select(
                    ToolExecutionRecord.id,
                    ToolExecutionRecord.message_id,
                    ToolExecutionRecord.call_id,
                    ToolExecutionRecord.tool_name,
                    ToolExecutionRecord.status,
                    ToolExecutionRecord.step_number,
                    ToolExecutionRecord.sequence_number,
                    ToolExecutionRecord.started_at,
                    ToolExecutionRecord.completed_at,
                    ToolExecutionRecord.duration_ms,
                    func.count(ToolExecutionRecord.id).over().label("record_total"),
                    func.count(ToolExecutionRecord.id)
                    .filter(ToolExecutionRecord.status == "failed")
                    .over()
                    .label("failed_total"),
                )
                .where(ToolExecutionRecord.conversation_id == conversation_id)
                .order_by(ToolExecutionRecord.started_at.desc(), ToolExecutionRecord.id.desc())
                .limit(limit)
            )
        )
        rows = result.all()
        items = tuple(
            ToolExecutionAuthority(
                id=row.id,
                message_id=row.message_id,
                call_id=row.call_id,
                tool_name=row.tool_name,
                status=row.status,
                error=None,
                step_number=row.step_number,
                sequence_number=row.sequence_number,
                started_at=row.started_at,
                completed_at=row.completed_at,
                duration_ms=row.duration_ms,
            )
            for row in rows
        )
        return ToolExecutionPageAuthority(
            items=items,
            total=int(rows[0].record_total) if rows else 0,
            failed_total=int(rows[0].failed_total) if rows else 0,
        )

    @staticmethod
    def _plan_node(record: PlanNodeModel) -> WorkspacePlanNodeAuthority:
        return WorkspacePlanNodeAuthority(
            id=record.id,
            plan_id=record.plan_id,
            workspace_task_id=cast(str, record.workspace_task_id),
            kind=record.kind,
            title=record.title,
            description=record.description,
            intent=record.intent,
            execution=record.execution,
            progress=dict(record.progress),
            assignee_agent_id=record.assignee_agent_id,
            current_attempt_id=record.current_attempt_id,
            created_at=record.created_at,
            updated_at=record.updated_at,
            completed_at=record.completed_at,
        )

    @classmethod
    def _hitl_kind(cls, request_type: str, metadata: dict[str, Any] | None) -> HITLKind | None:
        metadata_type: object = metadata.get("hitl_type") if metadata is not None else None
        candidate = metadata_type if isinstance(metadata_type, str) else request_type
        return cast(HITLKind, candidate) if candidate in cls._HITL_KINDS else None

    @classmethod
    def _safe_options(cls, value: object) -> tuple[dict[str, Any], ...]:
        if not isinstance(value, list):
            return ()
        raw_options = cast(list[object], value)
        options: list[dict[str, Any]] = []
        for raw_option in raw_options:
            if not isinstance(raw_option, Mapping):
                continue
            option_source = cast(Mapping[object, object], raw_option)
            option: dict[str, Any] = {}
            for key in cls._OPTION_KEYS:
                if key not in option_source:
                    continue
                raw_value = option_source[key]
                if isinstance(raw_value, str) and contains_secret_like_text(raw_value):
                    continue
                sanitized = sanitize_hitl_scalar(raw_value)
                if sanitized is not None:
                    option[key] = sanitized
            if option:
                options.append(option)
        return tuple(options)

    @staticmethod
    def _capability_mode(value: object) -> CapabilityMode | None:
        if not isinstance(value, Mapping):
            return None
        mapping = cast(Mapping[object, object], value)
        candidate = mapping.get("capability_mode")
        return cast(CapabilityMode, candidate) if candidate in {"work", "code"} else None

    @staticmethod
    def _string_tuple(value: object) -> tuple[str, ...]:
        if isinstance(value, list):
            items = cast(list[object], value)
        elif isinstance(value, tuple):
            items = list(cast(tuple[object, ...], value))
        else:
            return ()
        return tuple(item for item in items if isinstance(item, str) and item)


__all__ = ["SqlConversationSessionProjectionReader"]
