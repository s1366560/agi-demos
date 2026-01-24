"""
SQLAlchemy implementation of TaskRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.task.task_log import TaskLog
from src.domain.ports.repositories.task_repository import TaskRepository
from src.infrastructure.adapters.secondary.persistence.models import TaskLog as DBTaskLog

logger = logging.getLogger(__name__)


class SqlAlchemyTaskRepository(TaskRepository):
    """SQLAlchemy implementation of TaskRepository"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, task: TaskLog) -> None:
        """Save a task log (create or update)"""
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
            db_task = DBTaskLog(
                id=task.id,
                group_id=task.group_id,
                task_type=task.task_type,
                status=task.status,
                payload=task.payload,
                entity_id=task.entity_id,
                entity_type=task.entity_type,
                parent_task_id=task.parent_task_id,
                worker_id=task.worker_id,
                retry_count=task.retry_count,
                error_message=task.error_message,
                created_at=task.created_at,
                started_at=task.started_at,
                completed_at=task.completed_at,
                stopped_at=task.stopped_at,
            )
            self._session.add(db_task)

        await self._session.flush()

    async def find_by_id(self, task_id: str) -> Optional[TaskLog]:
        """Find a task by ID"""
        result = await self._session.execute(select(DBTaskLog).where(DBTaskLog.id == task_id))
        db_task = result.scalar_one_or_none()
        return self._to_domain(db_task) if db_task else None

    async def find_by_group(self, group_id: str, limit: int = 50, offset: int = 0) -> List[TaskLog]:
        """List all tasks in a group"""
        result = await self._session.execute(
            select(DBTaskLog).where(DBTaskLog.group_id == group_id).offset(offset).limit(limit)
        )
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def list_recent(self, limit: int = 100) -> List[TaskLog]:
        """List recent tasks across all groups"""
        result = await self._session.execute(
            select(DBTaskLog).order_by(DBTaskLog.created_at.desc()).limit(limit)
        )
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def list_by_status(self, status: str, limit: int = 50, offset: int = 0) -> List[TaskLog]:
        """List tasks by status"""
        result = await self._session.execute(
            select(DBTaskLog).where(DBTaskLog.status == status).offset(offset).limit(limit)
        )
        db_tasks = result.scalars().all()
        return [self._to_domain(t) for t in db_tasks]

    async def delete(self, task_id: str) -> None:
        """Delete a task"""
        result = await self._session.execute(select(DBTaskLog).where(DBTaskLog.id == task_id))
        db_task = result.scalar_one_or_none()
        if db_task:
            await self._session.delete(db_task)
            await self._session.flush()

    def _to_domain(self, db_task: DBTaskLog) -> TaskLog:
        """Convert database model to domain model"""
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
