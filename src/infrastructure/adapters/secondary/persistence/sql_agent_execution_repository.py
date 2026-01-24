"""
SQLAlchemy implementation of AgentExecutionRepository.
"""

import logging
from typing import List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import AgentExecution, ExecutionStatus
from src.domain.ports.repositories.agent_repository import AgentExecutionRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    AgentExecution as DBAgentExecution,
)

logger = logging.getLogger(__name__)


class SqlAlchemyAgentExecutionRepository(AgentExecutionRepository):
    """SQLAlchemy implementation of AgentExecutionRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, execution: AgentExecution) -> None:
        """Save an agent execution (create or update)."""
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
            db_execution = DBAgentExecution(
                id=execution.id,
                conversation_id=execution.conversation_id,
                message_id=execution.message_id,
                status=execution.status.value,
                thought=execution.thought,
                action=execution.action,
                observation=execution.observation,
                tool_name=execution.tool_name,
                tool_input=execution.tool_input,
                tool_output=execution.tool_output,
                meta=execution.metadata,
                started_at=execution.started_at,
                completed_at=execution.completed_at,
            )
            self._session.add(db_execution)

        await self._session.flush()

    async def find_by_id(self, execution_id: str) -> Optional[AgentExecution]:
        """Find an execution by its ID."""
        result = await self._session.execute(
            select(DBAgentExecution).where(DBAgentExecution.id == execution_id)
        )
        db_execution = result.scalar_one_or_none()
        return self._to_domain(db_execution) if db_execution else None

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

    @staticmethod
    def _to_domain(db_execution: DBAgentExecution) -> AgentExecution:
        """Convert database model to domain model."""
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
