"""SQLAlchemy implementation of :class:`PendingReviewRepository`."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any, override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.agent.conversation.pending_review import (
    PendingReview,
    PendingReviewStatus,
)
from src.domain.ports.agent.pending_review_repository import (
    PendingReviewRepository,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    PendingReviewModel,
)

__all__ = ["SqlPendingReviewRepository"]


def _to_domain(row: PendingReviewModel) -> PendingReview:
    return PendingReview(
        id=row.id,
        conversation_id=row.conversation_id,
        scope_agent_id=row.scope_agent_id,
        effective_category=row.effective_category,
        declared_category=row.declared_category,
        visibility=row.visibility,
        urgency=row.urgency,
        question=row.question,
        context=row.context,
        rationale=row.rationale,
        proposed_fallback=row.proposed_fallback,
        status=PendingReviewStatus(row.status),
        created_at=row.created_at,
        resolved_at=row.resolved_at,
        resolution_payload=row.resolution_payload,
        structurally_upgraded=row.structurally_upgraded,
        metadata=dict(row.meta or {}),
    )


class SqlPendingReviewRepository(PendingReviewRepository):
    """Persist pending reviews to ``pending_reviews``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def create(self, review: PendingReview) -> PendingReview:
        review_id = review.id or str(uuid.uuid4())
        row = PendingReviewModel(
            id=review_id,
            conversation_id=review.conversation_id,
            scope_agent_id=review.scope_agent_id,
            effective_category=review.effective_category,
            declared_category=review.declared_category,
            visibility=review.visibility,
            urgency=review.urgency,
            question=review.question,
            context=review.context,
            rationale=review.rationale,
            proposed_fallback=review.proposed_fallback,
            status=review.status.value,
            structurally_upgraded=review.structurally_upgraded,
            resolved_at=review.resolved_at,
            resolution_payload=review.resolution_payload,
            meta=dict(review.metadata or {}),
        )
        self._session.add(row)
        await self._session.flush()
        review.id = review_id
        return review

    @override
    async def get(self, review_id: str) -> PendingReview | None:
        result = await self._session.execute(
            select(PendingReviewModel).where(PendingReviewModel.id == review_id)
        )
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    @override
    async def list_open(self, conversation_id: str) -> list[PendingReview]:
        result = await self._session.execute(
            select(PendingReviewModel)
            .where(
                PendingReviewModel.conversation_id == conversation_id,
                PendingReviewModel.status == PendingReviewStatus.OPEN.value,
            )
            .order_by(PendingReviewModel.created_at.asc())
        )
        return [_to_domain(row) for row in result.scalars().all()]

    @override
    async def update_status(
        self,
        review_id: str,
        status: PendingReviewStatus,
        resolution_payload: dict[str, Any] | None = None,
    ) -> PendingReview | None:
        result = await self._session.execute(
            select(PendingReviewModel).where(PendingReviewModel.id == review_id)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        row.status = status.value
        if resolution_payload is not None:
            row.resolution_payload = resolution_payload
        if status is not PendingReviewStatus.OPEN:
            row.resolved_at = datetime.now(UTC)
        await self._session.flush()
        return _to_domain(row)
