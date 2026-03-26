"""SQLAlchemy repository for WorkspaceTask persistence."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.workspace.workspace_task import WorkspaceTask, WorkspaceTaskStatus
from src.domain.ports.repositories.workspace.workspace_task_repository import (
    WorkspaceTaskRepository,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceTaskModel


class SqlWorkspaceTaskRepository(
    BaseRepository[WorkspaceTask, WorkspaceTaskModel], WorkspaceTaskRepository
):
    """SQLAlchemy implementation of WorkspaceTaskRepository."""

    _model_class = WorkspaceTaskModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def find_by_workspace(
        self,
        workspace_id: str,
        status: WorkspaceTaskStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[WorkspaceTask]:
        query = select(WorkspaceTaskModel).where(WorkspaceTaskModel.workspace_id == workspace_id)
        if status is not None:
            query = query.where(WorkspaceTaskModel.status == status.value)
        query = query.order_by(WorkspaceTaskModel.created_at.desc()).offset(offset).limit(limit)
        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [t for row in rows if (t := self._to_domain(row)) is not None]

    def _to_domain(self, db_task: WorkspaceTaskModel | None) -> WorkspaceTask | None:
        if db_task is None:
            return None

        return WorkspaceTask(
            id=db_task.id,
            workspace_id=db_task.workspace_id,
            title=db_task.title,
            description=db_task.description,
            created_by=db_task.created_by,
            assignee_user_id=db_task.assignee_user_id,
            assignee_agent_id=db_task.assignee_agent_id,
            status=WorkspaceTaskStatus(db_task.status),
            priority=db_task.priority,
            estimated_effort=db_task.estimated_effort,
            blocker_reason=db_task.blocker_reason,
            metadata=db_task.metadata_json or {},
            created_at=db_task.created_at,
            updated_at=db_task.updated_at,
            completed_at=db_task.completed_at,
            archived_at=db_task.archived_at,
        )

    def _to_db(self, domain_entity: WorkspaceTask) -> WorkspaceTaskModel:
        return WorkspaceTaskModel(
            id=domain_entity.id,
            workspace_id=domain_entity.workspace_id,
            title=domain_entity.title,
            description=domain_entity.description,
            created_by=domain_entity.created_by,
            assignee_user_id=domain_entity.assignee_user_id,
            assignee_agent_id=domain_entity.assignee_agent_id,
            status=domain_entity.status.value,
            priority=domain_entity.priority,
            estimated_effort=domain_entity.estimated_effort,
            blocker_reason=domain_entity.blocker_reason,
            metadata_json=domain_entity.metadata,
            created_at=domain_entity.created_at,
            updated_at=domain_entity.updated_at,
            completed_at=domain_entity.completed_at,
            archived_at=domain_entity.archived_at,
        )

    def _update_fields(self, db_model: WorkspaceTaskModel, domain_entity: WorkspaceTask) -> None:
        db_model.title = domain_entity.title
        db_model.description = domain_entity.description
        db_model.assignee_user_id = domain_entity.assignee_user_id
        db_model.assignee_agent_id = domain_entity.assignee_agent_id
        db_model.status = domain_entity.status.value
        db_model.priority = domain_entity.priority
        db_model.estimated_effort = domain_entity.estimated_effort
        db_model.blocker_reason = domain_entity.blocker_reason
        db_model.metadata_json = domain_entity.metadata
        db_model.completed_at = domain_entity.completed_at
        db_model.archived_at = domain_entity.archived_at
        db_model.updated_at = domain_entity.updated_at
