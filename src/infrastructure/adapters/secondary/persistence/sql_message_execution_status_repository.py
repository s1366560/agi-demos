"""
V2 SQLAlchemy implementation of MessageExecutionStatusRepository using BaseRepository.

This repository manages the message execution status in PostgreSQL,
enabling event stream recovery after page refresh.

Note: This is different from sql_agent_execution_repository.py which tracks
individual Think-Act-Observe cycles. This repository tracks the overall
message generation status.
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.execution_status import AgentExecution, AgentExecutionStatus
from src.domain.ports.repositories.agent_execution_repository import (
    AgentExecutionRepositoryPort,
)
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository

logger = logging.getLogger(__name__)


class SqlMessageExecutionStatusRepository(
    BaseRepository[AgentExecution, object], AgentExecutionRepositoryPort
):
    """
    V2 SQLAlchemy implementation of message execution status tracking using BaseRepository.

    This repository tracks the overall message generation status,
    enabling event stream recovery after page refresh.
    """

    # This repository doesn't use a standard model for CRUD
    _model_class = None

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)
        self._session = session

    def _to_domain(self, model) -> AgentExecution:
        """Convert database model to domain entity."""
        return AgentExecution(
            id=model.id,
            conversation_id=model.conversation_id,
            message_id=model.message_id,
            status=AgentExecutionStatus(model.status),
            last_event_sequence=model.last_event_sequence,
            started_at=model.started_at,
            completed_at=model.completed_at,
            error_message=model.error_message,
            tenant_id=model.tenant_id,
            project_id=model.project_id,
        )

    def _to_model(self, entity: AgentExecution):
        """Convert domain entity to database model."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        return MessageExecutionStatusModel(
            id=entity.id,
            conversation_id=entity.conversation_id,
            message_id=entity.message_id,
            tenant_id=entity.tenant_id,
            project_id=entity.project_id,
            status=entity.status.value,
            last_event_sequence=entity.last_event_sequence,
            error_message=entity.error_message,
            started_at=entity.started_at,
            completed_at=entity.completed_at,
        )

    async def create(self, execution: AgentExecution) -> AgentExecution:
        """Create a new execution record."""
        model = self._to_model(execution)
        self._session.add(model)
        await self._session.flush()
        logger.info(
            f"Created message execution status: id={execution.id}, "
            f"conversation={execution.conversation_id}, status={execution.status.value}"
        )
        return execution

    async def get_by_id(self, execution_id: str) -> Optional[AgentExecution]:
        """Get execution by ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        result = await self._session.execute(
            select(MessageExecutionStatusModel).where(
                MessageExecutionStatusModel.id == execution_id
            )
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_by_message_id(
        self,
        message_id: str,
        conversation_id: Optional[str] = None,
    ) -> Optional[AgentExecution]:
        """Get execution by message ID."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        query = select(MessageExecutionStatusModel).where(
            MessageExecutionStatusModel.message_id == message_id
        )
        if conversation_id:
            query = query.where(MessageExecutionStatusModel.conversation_id == conversation_id)

        result = await self._session.execute(query)
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def get_running_by_conversation(
        self,
        conversation_id: str,
    ) -> Optional[AgentExecution]:
        """Get the currently running execution for a conversation."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        result = await self._session.execute(
            select(MessageExecutionStatusModel)
            .where(MessageExecutionStatusModel.conversation_id == conversation_id)
            .where(MessageExecutionStatusModel.status == AgentExecutionStatus.RUNNING.value)
            .order_by(MessageExecutionStatusModel.started_at.desc())
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def update_status(
        self,
        execution_id: str,
        status: AgentExecutionStatus,
        error_message: Optional[str] = None,
    ) -> Optional[AgentExecution]:
        """Update execution status."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        update_data = {
            "status": status.value,
        }

        if status in (
            AgentExecutionStatus.COMPLETED,
            AgentExecutionStatus.FAILED,
            AgentExecutionStatus.CANCELLED,
        ):
            update_data["completed_at"] = datetime.utcnow()

        if error_message:
            update_data["error_message"] = error_message

        result = await self._session.execute(
            update(MessageExecutionStatusModel)
            .where(MessageExecutionStatusModel.id == execution_id)
            .values(**update_data)
            .returning(MessageExecutionStatusModel)
        )
        model = result.scalar_one_or_none()

        if model:
            logger.info(
                f"Updated message execution status: id={execution_id}, status={status.value}"
            )
            return self._to_domain(model)
        return None

    async def update_sequence(
        self,
        execution_id: str,
        sequence: int,
    ) -> Optional[AgentExecution]:
        """Update the last event sequence number."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        result = await self._session.execute(
            update(MessageExecutionStatusModel)
            .where(MessageExecutionStatusModel.id == execution_id)
            .where(MessageExecutionStatusModel.last_event_sequence < sequence)
            .values(last_event_sequence=sequence)
            .returning(MessageExecutionStatusModel)
        )
        model = result.scalar_one_or_none()
        return self._to_domain(model) if model else None

    async def delete(self, execution_id: str) -> bool:
        """Delete an execution record."""
        from src.infrastructure.adapters.secondary.persistence.models import (
            MessageExecutionStatus as MessageExecutionStatusModel,
        )

        result = await self._session.execute(
            select(MessageExecutionStatusModel).where(
                MessageExecutionStatusModel.id == execution_id
            )
        )
        model = result.scalar_one_or_none()
        if model:
            await self._session.delete(model)
            logger.info(f"Deleted message execution status: id={execution_id}")
            return True
        return False
