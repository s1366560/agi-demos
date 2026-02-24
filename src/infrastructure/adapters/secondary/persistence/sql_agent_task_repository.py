"""SQL implementation of AgentTaskRepository."""

import logging
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.task import AgentTask, TaskPriority, TaskStatus
from src.domain.ports.repositories.agent_task_repository import AgentTaskRepository
from src.infrastructure.adapters.secondary.persistence.models import AgentTaskModel

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
            delete(AgentTaskModel).where(
                AgentTaskModel.conversation_id == conversation_id
            )
        )
        # Insert new
        for task in tasks:
            task.conversation_id = conversation_id
            self._session.add(self._to_model(task))
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

        result = await self._session.execute(query)
        rows = result.scalars().all()
        return [self._to_domain(r) for r in rows]

    async def find_by_id(self, task_id: str) -> AgentTask | None:
        """Find a task by ID."""
        model = await self._session.get(AgentTaskModel, task_id)
        return self._to_domain(model) if model else None

    async def update(self, task_id: str, **fields) -> AgentTask | None:
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
            delete(AgentTaskModel).where(
                AgentTaskModel.conversation_id == conversation_id
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
            status=TaskStatus(model.status),
            priority=TaskPriority(model.priority),
            order_index=model.order_index,
            created_at=model.created_at or datetime.now(UTC),
            updated_at=model.updated_at or model.created_at or datetime.now(UTC),
        )
