"""SQL repository for Agent session snapshots."""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import AgentSessionSnapshot


class SqlAgentSessionSnapshotRepository:
    """SQLAlchemy repository for Agent session snapshots."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_snapshot(self, snapshot: AgentSessionSnapshot) -> None:
        self._session.add(snapshot)

    async def get_latest_by_request_id(self, request_id: str) -> AgentSessionSnapshot | None:
        stmt = (
            select(AgentSessionSnapshot)
            .where(AgentSessionSnapshot.request_id == request_id)
            .order_by(AgentSessionSnapshot.created_at.desc())
            .limit(1)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_request_id(self, request_id: str) -> int:
        stmt = delete(AgentSessionSnapshot).where(AgentSessionSnapshot.request_id == request_id)
        result = await self._session.execute(stmt)
        return result.rowcount or 0
