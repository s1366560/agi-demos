"""SQL implementation of AgentTaskRepository."""

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.domain.ports.repositories.agent_task_repository import AgentTaskRepository
from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentPlanVersionModel,
    AgentTaskModel,
)

logger = logging.getLogger(__name__)


class SqlAgentTaskRepository(AgentTaskRepository):
    """SQLAlchemy implementation of AgentTaskRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, task: AgentTask) -> None:
        """Save a single task (upsert)."""
        existing = await self._session.get(AgentTaskModel, task.id)
        if existing:
            existing.content = task.content
            existing.title = task.title
            existing.description = task.description
            existing.estimated_duration_seconds = task.estimated_duration_seconds
            existing.started_at = task.started_at
            existing.completed_at = task.completed_at
            existing.result_summary = task.result_summary
            existing.evidence_refs = list(task.evidence_refs)
            existing.status = task.status.value
            existing.priority = task.priority.value
            existing.order_index = task.order_index
            existing.updated_at = datetime.now(UTC)
        else:
            model = self._to_model(task)
            self._session.add(model)
        await self._session.flush()

    async def save_all(self, conversation_id: str, tasks: list[AgentTask]) -> None:
        """Replace all tasks for a conversation (atomic)."""
        # Delete existing
        await self._session.execute(
            refresh_select_statement(
                delete(AgentTaskModel).where(AgentTaskModel.conversation_id == conversation_id)
            )
        )
        # Insert new
        for task in tasks:
            task.conversation_id = conversation_id
            self._session.add(self._to_model(task))
        latest_version = await self._session.scalar(
            select(func.max(AgentPlanVersionModel.version)).where(
                AgentPlanVersionModel.conversation_id == conversation_id
            )
        )
        self._session.add(
            AgentPlanVersionModel(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                version=(latest_version or 0) + 1,
                status="draft",
                tasks_json=[task.to_dict() for task in tasks],
                policy_revision=None,
            )
        )
        await self._session.flush()

    async def find_by_conversation(
        self, conversation_id: str, status: str | None = None
    ) -> list[AgentTask]:
        """Find all tasks for a conversation."""
        query = (
            select(AgentTaskModel)
            .where(AgentTaskModel.conversation_id == conversation_id)
            .order_by(AgentTaskModel.order_index)
        )
        if status:
            query = query.where(AgentTaskModel.status == status)

        result = await self._session.execute(refresh_select_statement(query))
        rows = result.scalars().all()
        return [self._to_domain(r) for r in rows]

    async def find_by_id(self, task_id: str) -> AgentTask | None:
        """Find a task by ID."""
        model = await self._session.get(AgentTaskModel, task_id)
        return self._to_domain(model) if model else None

    async def update(self, task_id: str, **fields: Any) -> AgentTask | None:
        """Update specific fields on a task."""
        model = await self._session.get(AgentTaskModel, task_id)
        if not model:
            return None

        for key, value in fields.items():
            if hasattr(model, key):
                setattr(model, key, value)
        model.updated_at = datetime.now(UTC)
        await self._session.flush()
        return self._to_domain(model)

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all tasks for a conversation."""
        await self._session.execute(
            refresh_select_statement(
                delete(AgentTaskModel).where(AgentTaskModel.conversation_id == conversation_id)
            )
        )
        await self._session.flush()

    @staticmethod
    def _to_model(task: AgentTask) -> AgentTaskModel:
        """Convert domain entity to DB model."""
        return AgentTaskModel(
            id=task.id,
            conversation_id=task.conversation_id,
            content=task.content,
            title=task.title,
            description=task.description,
            estimated_duration_seconds=task.estimated_duration_seconds,
            started_at=task.started_at,
            completed_at=task.completed_at,
            result_summary=task.result_summary,
            evidence_refs=list(task.evidence_refs),
            status=task.status.value,
            priority=task.priority.value,
            order_index=task.order_index,
        )

    @staticmethod
    def _to_domain(model: AgentTaskModel) -> AgentTask:
        """Convert DB model to domain entity."""
        return AgentTask(
            id=model.id,
            conversation_id=model.conversation_id,
            content=model.content,
            title=model.title,
            description=model.description,
            estimated_duration_seconds=model.estimated_duration_seconds,
            started_at=model.started_at,
            completed_at=model.completed_at,
            result_summary=model.result_summary,
            evidence_refs=list(model.evidence_refs or []),
            status=TaskStatus(model.status),
            priority=TaskPriority(model.priority),
            order_index=model.order_index,
            created_at=model.created_at or datetime.now(UTC),
            updated_at=model.updated_at or model.created_at or datetime.now(UTC),
        )
