"""SQLAlchemy repository for WorkspaceTaskSessionAttempt persistence."""

from datetime import datetime
from typing import override

from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task_session_attempt import (
    WorkspaceTaskSessionAttempt,
    WorkspaceTaskSessionAttemptStatus,
)
from src.domain.ports.repositories.workspace.workspace_task_session_attempt_repository import (
    WorkspaceTaskSessionAttemptRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import (
    BaseRepository,
    refresh_select_statement,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecutionEvent,
    WorkspaceTaskSessionAttemptModel,
)


class SqlWorkspaceTaskSessionAttemptRepository(
    BaseRepository[WorkspaceTaskSessionAttempt, WorkspaceTaskSessionAttemptModel],
    WorkspaceTaskSessionAttemptRepository,
):
    """SQLAlchemy implementation of WorkspaceTaskSessionAttemptRepository."""

    _model_class = WorkspaceTaskSessionAttemptModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    @override
    async def lock_attempt_creation(self, workspace_task_id: str) -> None:
        """Serialize per-task attempt creation across concurrent launch paths."""
        get_bind = getattr(self._session, "get_bind", None)
        if callable(get_bind):
            bind = get_bind()
            dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
            if dialect_name and dialect_name != "postgresql":
                return

        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:workspace_task_id, 0))"),
            {"workspace_task_id": workspace_task_id},
        )

    @override
    async def find_by_workspace_task_id(
        self,
        workspace_task_id: str,
        *,
        statuses: list[WorkspaceTaskSessionAttemptStatus] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTaskSessionAttempt]:
        stmt = select(WorkspaceTaskSessionAttemptModel).where(
            WorkspaceTaskSessionAttemptModel.workspace_task_id == workspace_task_id
        )
        if statuses:
            stmt = stmt.where(
                WorkspaceTaskSessionAttemptModel.status.in_([status.value for status in statuses])
            )
        stmt = (
            stmt.order_by(WorkspaceTaskSessionAttemptModel.attempt_number.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    async def find_active_by_workspace_task_id(
        self, workspace_task_id: str
    ) -> WorkspaceTaskSessionAttempt | None:
        stmt = (
            select(WorkspaceTaskSessionAttemptModel)
            .where(WorkspaceTaskSessionAttemptModel.workspace_task_id == workspace_task_id)
            .where(
                WorkspaceTaskSessionAttemptModel.status.in_(
                    [
                        WorkspaceTaskSessionAttemptStatus.PENDING.value,
                        WorkspaceTaskSessionAttemptStatus.RUNNING.value,
                        WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
                    ]
                )
            )
            .order_by(WorkspaceTaskSessionAttemptModel.attempt_number.desc())
            .limit(1)
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_by_conversation_id(
        self, conversation_id: str
    ) -> WorkspaceTaskSessionAttempt | None:
        stmt = (
            select(WorkspaceTaskSessionAttemptModel)
            .where(WorkspaceTaskSessionAttemptModel.conversation_id == conversation_id)
            .limit(1)
        )
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return self._to_domain(result.scalar_one_or_none())

    @override
    async def find_stale_non_terminal(
        self,
        *,
        older_than: datetime,
        limit: int = 500,
        workspace_id: str | None = None,
    ) -> list[WorkspaceTaskSessionAttempt]:
        """Return non-terminal attempts whose last activity is older than ``older_than``.

        Falls back to ``created_at`` for attempts that never had an update (so a
        freshly-inserted PENDING attempt whose worker never started will be
        recovered once it ages past the threshold).
        """
        non_terminal = [
            WorkspaceTaskSessionAttemptStatus.PENDING.value,
            WorkspaceTaskSessionAttemptStatus.RUNNING.value,
            WorkspaceTaskSessionAttemptStatus.AWAITING_LEADER_ADJUDICATION.value,
        ]
        attempt_activity = func.coalesce(
            WorkspaceTaskSessionAttemptModel.updated_at,
            WorkspaceTaskSessionAttemptModel.created_at,
        )
        latest_conversation_event = (
            select(func.max(AgentExecutionEvent.created_at))
            .where(
                AgentExecutionEvent.conversation_id
                == WorkspaceTaskSessionAttemptModel.conversation_id
            )
            .correlate(WorkspaceTaskSessionAttemptModel)
            .scalar_subquery()
        )
        conversation_activity = func.coalesce(latest_conversation_event, attempt_activity)
        last_activity = case(
            (conversation_activity > attempt_activity, conversation_activity),
            else_=attempt_activity,
        )
        stmt = (
            select(WorkspaceTaskSessionAttemptModel)
            .where(WorkspaceTaskSessionAttemptModel.status.in_(non_terminal))
            .where(last_activity < older_than)
        )
        if workspace_id:
            stmt = stmt.where(WorkspaceTaskSessionAttemptModel.workspace_id == workspace_id)
        stmt = stmt.order_by(last_activity.asc()).limit(limit)
        result = await self._session.execute(
            refresh_select_statement(self._refresh_statement(stmt))
        )
        return [d for row in result.scalars().all() if (d := self._to_domain(row)) is not None]

    @override
    def _to_domain(
        self, db_model: WorkspaceTaskSessionAttemptModel | None
    ) -> WorkspaceTaskSessionAttempt | None:
        if db_model is None:
            return None
        return WorkspaceTaskSessionAttempt(
            id=db_model.id,
            workspace_task_id=db_model.workspace_task_id,
            root_goal_task_id=db_model.root_goal_task_id,
            workspace_id=db_model.workspace_id,
            attempt_number=db_model.attempt_number,
            status=WorkspaceTaskSessionAttemptStatus(db_model.status),
            conversation_id=db_model.conversation_id,
            worker_agent_id=db_model.worker_agent_id,
            leader_agent_id=db_model.leader_agent_id,
            candidate_summary=db_model.candidate_summary,
            candidate_artifacts=list(db_model.candidate_artifacts_json or []),
            candidate_verifications=list(db_model.candidate_verifications_json or []),
            leader_feedback=db_model.leader_feedback,
            adjudication_reason=db_model.adjudication_reason,
            created_at=db_model.created_at,
            updated_at=db_model.updated_at,
            completed_at=db_model.completed_at,
        )

    @override
    def _to_db(
        self, domain_entity: WorkspaceTaskSessionAttempt
    ) -> WorkspaceTaskSessionAttemptModel:
        return WorkspaceTaskSessionAttemptModel(
            id=domain_entity.id,
            workspace_task_id=domain_entity.workspace_task_id,
            root_goal_task_id=domain_entity.root_goal_task_id,
            workspace_id=domain_entity.workspace_id,
            attempt_number=domain_entity.attempt_number,
            status=domain_entity.status.value,
            conversation_id=domain_entity.conversation_id,
            worker_agent_id=domain_entity.worker_agent_id,
            leader_agent_id=domain_entity.leader_agent_id,
            candidate_summary=domain_entity.candidate_summary,
            candidate_artifacts_json=domain_entity.candidate_artifacts,
            candidate_verifications_json=domain_entity.candidate_verifications,
            leader_feedback=domain_entity.leader_feedback,
            adjudication_reason=domain_entity.adjudication_reason,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            completed_at=domain_entity.completed_at,
        )

    @override
    def _update_fields(
        self,
        db_model: WorkspaceTaskSessionAttemptModel,
        domain_entity: WorkspaceTaskSessionAttempt,
    ) -> None:
        db_model.status = domain_entity.status.value
        db_model.conversation_id = domain_entity.conversation_id
        db_model.worker_agent_id = domain_entity.worker_agent_id
        db_model.leader_agent_id = domain_entity.leader_agent_id
        db_model.candidate_summary = domain_entity.candidate_summary
        db_model.candidate_artifacts_json = domain_entity.candidate_artifacts
        db_model.candidate_verifications_json = domain_entity.candidate_verifications
        db_model.leader_feedback = domain_entity.leader_feedback
        db_model.adjudication_reason = domain_entity.adjudication_reason
        db_model.updated_at = domain_entity.updated_at
        db_model.completed_at = domain_entity.completed_at
