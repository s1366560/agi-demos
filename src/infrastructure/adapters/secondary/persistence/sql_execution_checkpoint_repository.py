"""
SQLAlchemy implementation of ExecutionCheckpointRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ExecutionCheckpoint
from src.domain.ports.repositories.agent_repository import ExecutionCheckpointRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    ExecutionCheckpoint as DBExecutionCheckpoint,
)

logger = logging.getLogger(__name__)


class SqlAlchemyExecutionCheckpointRepository(ExecutionCheckpointRepository):
    """SQLAlchemy implementation of ExecutionCheckpointRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, checkpoint: ExecutionCheckpoint) -> None:
        """Save an execution checkpoint."""
        db_checkpoint = DBExecutionCheckpoint(
            id=checkpoint.id,
            conversation_id=checkpoint.conversation_id,
            message_id=checkpoint.message_id,
            checkpoint_type=str(checkpoint.checkpoint_type),
            execution_state=checkpoint.execution_state,
            step_number=checkpoint.step_number,
            created_at=checkpoint.created_at,
        )
        self._session.add(db_checkpoint)
        await self._session.flush()

    async def save_and_commit(self, checkpoint: ExecutionCheckpoint) -> None:
        """Save a checkpoint and commit immediately."""
        await self.save(checkpoint)
        await self._session.commit()

    async def get_latest(
        self,
        conversation_id: str,
        message_id: Optional[str] = None,
    ) -> Optional[ExecutionCheckpoint]:
        """Get the latest checkpoint for a conversation."""
        query = select(DBExecutionCheckpoint).where(
            DBExecutionCheckpoint.conversation_id == conversation_id
        )

        if message_id:
            query = query.where(DBExecutionCheckpoint.message_id == message_id)

        query = query.order_by(desc(DBExecutionCheckpoint.created_at)).limit(1)

        result = await self._session.execute(query)
        db_checkpoint = result.scalar_one_or_none()
        return self._to_domain(db_checkpoint) if db_checkpoint else None

    async def get_by_type(
        self,
        conversation_id: str,
        checkpoint_type: str,
        limit: int = 10,
    ) -> List[ExecutionCheckpoint]:
        """Get checkpoints of a specific type for a conversation."""
        result = await self._session.execute(
            select(DBExecutionCheckpoint)
            .where(
                DBExecutionCheckpoint.conversation_id == conversation_id,
                DBExecutionCheckpoint.checkpoint_type == checkpoint_type,
            )
            .order_by(desc(DBExecutionCheckpoint.created_at))
            .limit(limit)
        )
        db_checkpoints = result.scalars().all()
        return [self._to_domain(c) for c in db_checkpoints]

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all checkpoints for a conversation."""
        await self._session.execute(
            delete(DBExecutionCheckpoint).where(
                DBExecutionCheckpoint.conversation_id == conversation_id
            )
        )
        await self._session.flush()

    @staticmethod
    def _to_domain(db_checkpoint: DBExecutionCheckpoint) -> ExecutionCheckpoint:
        """Convert database model to domain model."""
        return ExecutionCheckpoint(
            id=db_checkpoint.id,
            conversation_id=db_checkpoint.conversation_id,
            message_id=db_checkpoint.message_id,
            checkpoint_type=db_checkpoint.checkpoint_type,
            execution_state=db_checkpoint.execution_state or {},
            step_number=db_checkpoint.step_number,
            created_at=db_checkpoint.created_at,
        )
