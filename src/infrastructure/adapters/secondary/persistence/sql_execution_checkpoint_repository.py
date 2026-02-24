"""
V2 SQLAlchemy implementation of ExecutionCheckpointRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements ExecutionCheckpointRepository interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods
"""

import logging

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ExecutionCheckpoint
from src.domain.ports.repositories.agent_repository import ExecutionCheckpointRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    ExecutionCheckpoint as DBExecutionCheckpoint,
)

logger = logging.getLogger(__name__)


class SqlExecutionCheckpointRepository(
    BaseRepository[ExecutionCheckpoint, DBExecutionCheckpoint], ExecutionCheckpointRepository
):
    """
    V2 SQLAlchemy implementation of ExecutionCheckpointRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    checkpoint-specific query methods.
    """

    # Define the SQLAlchemy model class
    _model_class = DBExecutionCheckpoint

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (checkpoint-specific queries) ===

    async def save(self, checkpoint: ExecutionCheckpoint) -> None:
        """Save an execution checkpoint."""
        db_checkpoint = self._to_db(checkpoint)
        self._session.add(db_checkpoint)
        await self._session.flush()

    async def save_and_commit(self, checkpoint: ExecutionCheckpoint) -> None:
        """Save a checkpoint and commit immediately."""
        await self.save(checkpoint)
        await self._session.commit()

    async def get_latest(
        self,
        conversation_id: str,
        message_id: str | None = None,
    ) -> ExecutionCheckpoint | None:
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
    ) -> list[ExecutionCheckpoint]:
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
        return [d for c in db_checkpoints if (d := self._to_domain(c)) is not None]

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all checkpoints for a conversation."""
        await self._session.execute(
            delete(DBExecutionCheckpoint).where(
                DBExecutionCheckpoint.conversation_id == conversation_id
            )
        )
        await self._session.flush()

    # === Conversion methods ===

    def _to_domain(self, db_checkpoint: DBExecutionCheckpoint | None) -> ExecutionCheckpoint | None:
        """
        Convert database model to domain model.

        Args:
            db_checkpoint: Database model instance or None

        Returns:
            Domain model instance or None
        """
        if db_checkpoint is None:
            return None

        return ExecutionCheckpoint(
            id=db_checkpoint.id,
            conversation_id=db_checkpoint.conversation_id,
            message_id=db_checkpoint.message_id,
            checkpoint_type=db_checkpoint.checkpoint_type,
            execution_state=db_checkpoint.execution_state or {},
            step_number=db_checkpoint.step_number,
            created_at=db_checkpoint.created_at,
        )

    def _to_db(self, domain_entity: ExecutionCheckpoint) -> DBExecutionCheckpoint:
        """
        Convert domain entity to database model.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBExecutionCheckpoint(
            id=domain_entity.id,
            conversation_id=domain_entity.conversation_id,
            message_id=domain_entity.message_id,
            checkpoint_type=str(domain_entity.checkpoint_type),
            execution_state=domain_entity.execution_state,
            step_number=domain_entity.step_number,
            created_at=domain_entity.created_at,
        )
