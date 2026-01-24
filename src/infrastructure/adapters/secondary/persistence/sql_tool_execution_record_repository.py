"""
SQLAlchemy implementation of ToolExecutionRecordRepository.
"""

import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent import ToolExecutionRecord
from src.domain.ports.repositories.agent_repository import ToolExecutionRecordRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    ToolExecutionRecord as DBToolExecutionRecord,
)

logger = logging.getLogger(__name__)


class SqlAlchemyToolExecutionRecordRepository(ToolExecutionRecordRepository):
    """SQLAlchemy implementation of ToolExecutionRecordRepository."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def save(self, record: ToolExecutionRecord) -> None:
        """Save a tool execution record (create or update)."""
        result = await self._session.execute(
            select(DBToolExecutionRecord).where(DBToolExecutionRecord.id == record.id)
        )
        db_record = result.scalar_one_or_none()

        if db_record:
            # Update existing record
            db_record.status = record.status
            db_record.tool_output = record.tool_output
            db_record.error = record.error
            db_record.completed_at = record.completed_at
            db_record.duration_ms = record.duration_ms
        else:
            # Create new record
            db_record = DBToolExecutionRecord(
                id=record.id,
                conversation_id=record.conversation_id,
                message_id=record.message_id,
                call_id=record.call_id,
                tool_name=record.tool_name,
                tool_input=record.tool_input,
                tool_output=record.tool_output,
                status=record.status,
                error=record.error,
                step_number=record.step_number,
                sequence_number=record.sequence_number,
                started_at=record.started_at,
                completed_at=record.completed_at,
                duration_ms=record.duration_ms,
            )
            self._session.add(db_record)

        await self._session.flush()

    async def save_and_commit(self, record: ToolExecutionRecord) -> None:
        """Save a tool execution record and commit immediately."""
        await self.save(record)
        await self._session.commit()

    async def find_by_id(self, record_id: str) -> Optional[ToolExecutionRecord]:
        """Find a tool execution record by its ID."""
        result = await self._session.execute(
            select(DBToolExecutionRecord).where(DBToolExecutionRecord.id == record_id)
        )
        db_record = result.scalar_one_or_none()
        return self._to_domain(db_record) if db_record else None

    async def find_by_call_id(self, call_id: str) -> Optional[ToolExecutionRecord]:
        """Find a tool execution record by its call ID."""
        result = await self._session.execute(
            select(DBToolExecutionRecord).where(DBToolExecutionRecord.call_id == call_id)
        )
        db_record = result.scalar_one_or_none()
        return self._to_domain(db_record) if db_record else None

    async def list_by_message(
        self,
        message_id: str,
        limit: int = 100,
    ) -> List[ToolExecutionRecord]:
        """List tool executions for a message."""
        result = await self._session.execute(
            select(DBToolExecutionRecord)
            .where(DBToolExecutionRecord.message_id == message_id)
            .order_by(DBToolExecutionRecord.sequence_number.asc())
            .limit(limit)
        )
        db_records = result.scalars().all()
        return [self._to_domain(r) for r in db_records]

    async def list_by_conversation(
        self,
        conversation_id: str,
        limit: int = 100,
    ) -> List[ToolExecutionRecord]:
        """List tool executions for a conversation."""
        result = await self._session.execute(
            select(DBToolExecutionRecord)
            .where(DBToolExecutionRecord.conversation_id == conversation_id)
            .order_by(DBToolExecutionRecord.started_at.asc())
            .limit(limit)
        )
        db_records = result.scalars().all()
        return [self._to_domain(r) for r in db_records]

    async def delete_by_conversation(self, conversation_id: str) -> None:
        """Delete all tool execution records in a conversation."""
        await self._session.execute(
            delete(DBToolExecutionRecord).where(
                DBToolExecutionRecord.conversation_id == conversation_id
            )
        )
        await self._session.flush()

    async def update_status(
        self,
        call_id: str,
        status: str,
        output: Optional[str] = None,
        error: Optional[str] = None,
        duration_ms: Optional[int] = None,
    ) -> None:
        """Update the status of a tool execution record."""
        update_values = {
            "status": status,
            "completed_at": datetime.utcnow(),
        }
        if output is not None:
            update_values["tool_output"] = output
        if error is not None:
            update_values["error"] = error
        if duration_ms is not None:
            update_values["duration_ms"] = duration_ms

        await self._session.execute(
            update(DBToolExecutionRecord)
            .where(DBToolExecutionRecord.call_id == call_id)
            .values(**update_values)
        )
        await self._session.commit()

    @staticmethod
    def _to_domain(db_record: DBToolExecutionRecord) -> ToolExecutionRecord:
        """Convert database model to domain model."""
        return ToolExecutionRecord(
            id=db_record.id,
            conversation_id=db_record.conversation_id,
            message_id=db_record.message_id,
            call_id=db_record.call_id,
            tool_name=db_record.tool_name,
            tool_input=db_record.tool_input or {},
            tool_output=db_record.tool_output,
            status=db_record.status,
            error=db_record.error,
            step_number=db_record.step_number,
            sequence_number=db_record.sequence_number,
            started_at=db_record.started_at,
            completed_at=db_record.completed_at,
            duration_ms=db_record.duration_ms,
        )
