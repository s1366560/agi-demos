"""SQLAlchemy implementation of :class:`DecisionLogRepository`."""

from __future__ import annotations

import uuid
from typing import override

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.conversation.decision_log import DecisionLogEntry
from src.domain.ports.agent.decision_log_repository import DecisionLogRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    DecisionLogModel,
)

__all__ = ["SqlDecisionLogRepository"]


def _to_domain(row: DecisionLogModel) -> DecisionLogEntry:
    return DecisionLogEntry(
        id=row.id,
        conversation_id=row.conversation_id,
        agent_id=row.agent_id,
        tool_name=row.tool_name,
        input_payload=dict(row.input_payload or {}),
        output_summary=row.output_summary,
        rationale=row.rationale,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
        metadata=dict(row.meta or {}),
    )


class SqlDecisionLogRepository(DecisionLogRepository):
    """Persist decision-log entries to ``decision_logs``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def append(self, entry: DecisionLogEntry) -> DecisionLogEntry:
        entry_id = entry.id or str(uuid.uuid4())
        row = DecisionLogModel(
            id=entry_id,
            conversation_id=entry.conversation_id,
            agent_id=entry.agent_id,
            tool_name=entry.tool_name,
            input_payload=dict(entry.input_payload or {}),
            output_summary=entry.output_summary,
            rationale=entry.rationale,
            latency_ms=entry.latency_ms,
            meta=dict(entry.metadata or {}),
        )
        self._session.add(row)
        await self._session.flush()
        return DecisionLogEntry(
            id=entry_id,
            conversation_id=entry.conversation_id,
            agent_id=entry.agent_id,
            tool_name=entry.tool_name,
            input_payload=dict(entry.input_payload or {}),
            output_summary=entry.output_summary,
            rationale=entry.rationale,
            latency_ms=entry.latency_ms,
            created_at=entry.created_at,
            metadata=dict(entry.metadata or {}),
        )

    @override
    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecisionLogEntry]:
        result = await self._session.execute(
            select(DecisionLogModel)
            .where(DecisionLogModel.conversation_id == conversation_id)
            .order_by(DecisionLogModel.created_at.asc())
            .offset(offset)
            .limit(limit)
        )
        return [_to_domain(row) for row in result.scalars().all()]

    @override
    async def count(self, conversation_id: str) -> int:
        result = await self._session.execute(
            select(func.count(DecisionLogModel.id)).where(
                DecisionLogModel.conversation_id == conversation_id
            )
        )
        return int(result.scalar_one())
