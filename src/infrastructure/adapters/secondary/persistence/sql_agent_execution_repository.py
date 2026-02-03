"""
V2 SQLAlchemy implementation of AgentExecutionRepository using BaseRepository.

This is a migrated version that:
- Extends BaseRepository for common CRUD operations
- Implements AgentExecutionRepository interface
- Maintains 100% compatibility with original implementation
- Uses standard _to_domain() and _to_db() conversion methods

Migration Benefits:
- ~70% reduction in boilerplate code
- Consistent error handling via BaseRepository
- Built-in transaction management
- Bulk operations support
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.agent_execution import AgentExecution, ExecutionStatus
from src.domain.ports.repositories.agent_repository import AgentExecutionRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecution as DBAgentExecution,
)

logger = logging.getLogger(__name__)


class SqlAgentExecutionRepository(
    BaseRepository[AgentExecution, DBAgentExecution], AgentExecutionRepository
):
    """
    V2 SQLAlchemy implementation of AgentExecutionRepository using BaseRepository.

    Leverages the base class for standard CRUD operations while providing
    agent execution-specific query methods.
    """

    # Define the SQLAlchemy model class
    _model_class = DBAgentExecution

    def __init__(self, session: AsyncSession) -> None:
        """
        Initialize the repository.

        Args:
            session: SQLAlchemy async session
        """
        super().__init__(session)

    # === Interface implementation (agent execution-specific queries) ===

    async def save(self, execution: AgentExecution) -> None:
        """
        Save an agent execution (create or update).

        This method overrides the base save to match the original interface
        which returns None instead of the entity.

        Args:
            execution: The agent execution to save
        """
        # Check if exists
        result = await self._session.execute(
            select(DBAgentExecution).where(DBAgentExecution.id == execution.id)
        )
        db_execution = result.scalar_one_or_none()

        if db_execution:
            # Update existing execution
            db_execution.status = execution.status.value
            db_execution.thought = execution.thought
            db_execution.action = execution.action
            db_execution.observation = execution.observation
            db_execution.tool_name = execution.tool_name
            db_execution.tool_input = execution.tool_input
            db_execution.tool_output = execution.tool_output
            db_execution.meta = execution.metadata
            db_execution.completed_at = execution.completed_at
        else:
            # Create new execution
            db_execution = self._to_db(execution)
            self._session.add(db_execution)

        await self._session.flush()

    async def list_by_message(self, message_id: str) -> List[AgentExecution]:
        """List executions for a message."""
        result = await self._session.execute(
            select(DBAgentExecution)
            .where(DBAgentExecution.message_id == message_id)
            .order_by(DBAgentExecution.started_at.asc())
        )
        db_executions = result.scalars().all()
        return [self._to_domain(e) for e in db_executions]

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> List[AgentExecution]:
        """List executions for a conversation."""
        result = await self._session.execute(
            select(DBAgentExecution)
            .where(DBAgentExecution.conversation_id == conversation_id)
            .order_by(DBAgentExecution.started_at.asc())
            .limit(limit)
        )
        db_executions = result.scalars().all()
        return [self._to_domain(e) for e in db_executions]

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all executions in a conversation."""
        await self._session.execute(
            delete(DBAgentExecution).where(DBAgentExecution.conversation_id == conversation_id)
        )
        await self._session.flush()

    # === Conversion methods ===

    def _to_domain(self, db_execution: Optional[DBAgentExecution]) -> Optional[AgentExecution]:
        """
        Convert database model to domain model.

        Args:
            db_execution: Database model instance or None

        Returns:
            Domain model instance or None
        """
        if db_execution is None:
            return None

        return AgentExecution(
            id=db_execution.id,
            conversation_id=db_execution.conversation_id,
            message_id=db_execution.message_id,
            status=ExecutionStatus(db_execution.status),
            thought=db_execution.thought,
            action=db_execution.action,
            observation=db_execution.observation,
            tool_name=db_execution.tool_name,
            tool_input=db_execution.tool_input or {},
            tool_output=db_execution.tool_output,
            metadata=db_execution.meta or {},
            started_at=db_execution.started_at,
            completed_at=db_execution.completed_at,
        )

    def _to_db(self, domain_entity: AgentExecution) -> DBAgentExecution:
        """
        Convert domain entity to database model.

        Args:
            domain_entity: Domain model instance

        Returns:
            Database model instance
        """
        return DBAgentExecution(
            id=domain_entity.id,
            conversation_id=domain_entity.conversation_id,
            message_id=domain_entity.message_id,
            status=domain_entity.status.value,
            thought=domain_entity.thought,
            action=domain_entity.action,
            observation=domain_entity.observation,
            tool_name=domain_entity.tool_name,
            tool_input=domain_entity.tool_input,
            tool_output=domain_entity.tool_output,
            meta=domain_entity.metadata,
            started_at=domain_entity.started_at,
            completed_at=domain_entity.completed_at,
        )

    def _update_fields(self, db_model: DBAgentExecution, domain_entity: AgentExecution) -> None:
        """
        Update database model fields from domain entity.

        Args:
            db_model: Database model to update
            domain_entity: Domain entity with new values
        """
        db_model.status = domain_entity.status.value
        db_model.thought = domain_entity.thought
        db_model.action = domain_entity.action
        db_model.observation = domain_entity.observation
        db_model.tool_name = domain_entity.tool_name
        db_model.tool_input = domain_entity.tool_input
        db_model.tool_output = domain_entity.tool_output
        db_model.meta = domain_entity.metadata
        db_model.completed_at = domain_entity.completed_at
