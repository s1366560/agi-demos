"""
V2 SQLAlchemy implementation of TaskRepository using BaseRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import TaskLog as DBTaskLog

logger = logging.getLogger(__name__)


class SqlTaskRepository(BaseRepository[TaskLog, DBTaskLog], TaskRepository):
    """V2 SQLAlchemy implementation of TaskRepository using BaseRepository."""

    _model_class = DBTaskLog

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save(self, task: TaskLog) -> None:
        """Save a task log (create or update)."""
        result = await self._session.execute(select(DBTaskLog).where(DBTaskLog.id == task.id))
        db_task = result.scalar_one_or_none()

        if db_task:
            # Update existing task
            db_task.status = task.status
            db_task.error_message = task.error_message
            db_task.started_at = task.started_at
            db_task.completed_at = task.completed_at
            db_task.stopped_at = task.stopped_at
            db_task.worker_id = task.worker_id
            db_task.retry_count = task.retry_count
        else:
            # Create new task
            db_task = self._to_db(task)
            self._session.add(db_task)

        await self._session.flush()

    async def find_by_id(self, task_id: str) -> Optional[TaskLog]:
        """Find a task by ID."""
        return await super().find_by_id(task_id)

    async def find_by_group(self, group_id: str, limit: int = 50, offset: int = 0) -> List[TaskLog]:
        """List all tasks in a group."""
        query = select(DBTaskLog).where(DBTaskLog.group_id == group_id)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def list_recent(self, limit: int = 100) -> List[TaskLog]:
        """List recent tasks across all groups."""
        query = select(DBTaskLog).order_by(DBTaskLog.created_at.desc()).limit(limit)
        result = await self._session.execute(query)
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def list_by_status(self, status: str, limit: int = 50, offset: int = 0) -> List[TaskLog]:
        """List tasks by status."""
        query = select(DBTaskLog).where(DBTaskLog.status == status)
        query = query.offset(offset).limit(limit)
        result = await self._session.execute(query)
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def delete(self, task_id: str) -> None:
        """Delete a task."""
        await super().delete(task_id)

    def _to_domain(self, db_task: Optional[DBTaskLog]) -> Optional[TaskLog]:
        """Convert database model to domain model."""
        if db_task is None:
            return None

        return TaskLog(
            id=db_task.id,
            group_id=db_task.group_id,
            task_type=db_task.task_type,
            status=db_task.status,
            payload=db_task.payload,
            entity_id=db_task.entity_id,
            entity_type=db_task.entity_type,
            parent_task_id=db_task.parent_task_id,
            worker_id=db_task.worker_id,
            retry_count=db_task.retry_count,
            error_message=db_task.error_message,
            created_at=db_task.created_at,
            started_at=db_task.started_at,
            completed_at=db_task.completed_at,
            stopped_at=db_task.stopped_at,
        )

    def _to_db(self, domain_entity: TaskLog) -> DBTaskLog:
        """Convert domain entity to database model."""
        return DBTaskLog(
            id=domain_entity.id,
            group_id=domain_entity.group_id,
            task_type=domain_entity.task_type,
            status=domain_entity.status,
            payload=domain_entity.payload,
            entity_id=domain_entity.entity_id,
            entity_type=domain_entity.entity_type,
            parent_task_id=domain_entity.parent_task_id,
            worker_id=domain_entity.worker_id,
            retry_count=domain_entity.retry_count,
            error_message=domain_entity.error_message,
            created_at=domain_entity.created_at,
            started_at=domain_entity.started_at,
            completed_at=domain_entity.completed_at,
            stopped_at=domain_entity.stopped_at,
        )
