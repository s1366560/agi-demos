"""SQLAlchemy repository for decision record persistence."""

from __future__ import annotations

from typing import override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.trust.decision_record import DecisionRecord
from src.domain.ports.repositories.decision_record_repository import (
    DecisionRecordRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    DecisionRecordModel,
)


class SqlDecisionRecordRepository(DecisionRecordRepository):
    """Standalone repository -- not extending BaseRepository."""

    def __init__(self, db: AsyncSession) -> None:
        self._session = db

    @override
    async def save(self, record: DecisionRecord) -> DecisionRecord:
        db_model = self._to_db(record)
        self._session.add(db_model)
        await self._session.flush()
        return record

    @override
    async def find_by_id(self, record_id: str) -> DecisionRecord | None:
        stmt = select(DecisionRecordModel).where(
            DecisionRecordModel.id == record_id,
            DecisionRecordModel.deleted_at.is_(None),
        )
        result = await self._session.execute(stmt)
        row = result.scalars().first()
        return self._to_domain(row) if row else None

    @override
    async def find_by_workspace(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        decision_type: str | None = None,
    ) -> list[DecisionRecord]:
        stmt = select(DecisionRecordModel).where(
            DecisionRecordModel.workspace_id == workspace_id,
            DecisionRecordModel.deleted_at.is_(None),
        )
        if agent_id is not None:
            stmt = stmt.where(
                DecisionRecordModel.agent_instance_id == agent_id,
            )
        if decision_type is not None:
            stmt = stmt.where(DecisionRecordModel.decision_type == decision_type)
        stmt = stmt.order_by(DecisionRecordModel.created_at.desc())
        result = await self._session.execute(stmt)
        return [self._to_domain(row) for row in result.scalars().all()]

    @override
    async def update(self, record: DecisionRecord) -> None:
        db_model = self._to_db(record)
        await self._session.merge(db_model)
        await self._session.flush()

    @staticmethod
    def _to_domain(row: DecisionRecordModel) -> DecisionRecord:
        return DecisionRecord(
            id=row.id,
            tenant_id=row.tenant_id,
            workspace_id=row.workspace_id,
            agent_instance_id=row.agent_instance_id,
            decision_type=row.decision_type,
            context_summary=row.context_summary,
            proposal=dict(row.proposal) if row.proposal else {},
            outcome=row.outcome,
            reviewer_id=row.reviewer_id,
            review_type=row.review_type,
            review_comment=row.review_comment,
            resolved_at=row.resolved_at,
            created_at=row.created_at,
            updated_at=row.updated_at,
            deleted_at=row.deleted_at,
        )

    @staticmethod
    def _to_db(record: DecisionRecord) -> DecisionRecordModel:
        return DecisionRecordModel(
            id=record.id,
            tenant_id=record.tenant_id,
            workspace_id=record.workspace_id,
            agent_instance_id=record.agent_instance_id,
            decision_type=record.decision_type,
            context_summary=record.context_summary,
            proposal=record.proposal,
            outcome=record.outcome,
            reviewer_id=record.reviewer_id,
            review_type=record.review_type,
            review_comment=record.review_comment,
            resolved_at=record.resolved_at,
            created_at=record.created_at,
            updated_at=record.updated_at,
            deleted_at=record.deleted_at,
        )
