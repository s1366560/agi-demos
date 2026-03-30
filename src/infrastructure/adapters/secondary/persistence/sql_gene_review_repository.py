from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import override

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.instance_gene import GeneReview
from src.domain.ports.repositories.gene_review_repository import GeneReviewRepository
from src.infrastructure.adapters.secondary.common.base_repository import BaseRepository
from src.infrastructure.adapters.secondary.persistence.models import GeneReviewModel

logger = logging.getLogger(__name__)


class SqlGeneReviewRepository(BaseRepository[GeneReview, GeneReviewModel], GeneReviewRepository):
    _model_class = GeneReviewModel

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._session = session

    @override
    def _to_domain(self, db_model: GeneReviewModel | None) -> GeneReview | None:
        if db_model is None:
            return None
        return GeneReview(
            id=db_model.id,
            gene_id=db_model.gene_id,
            user_id=db_model.user_id,
            rating=db_model.rating,
            content=db_model.content,
            created_at=db_model.created_at,
            deleted_at=db_model.deleted_at,
        )

    @override
    def _to_db(self, domain_entity: GeneReview) -> GeneReviewModel:
        return GeneReviewModel(
            id=domain_entity.id,
            gene_id=domain_entity.gene_id,
            user_id=domain_entity.user_id,
            rating=domain_entity.rating,
            content=domain_entity.content,
            created_at=domain_entity.created_at,
            deleted_at=domain_entity.deleted_at,
        )

    @override
    def _update_fields(self, db_model: GeneReviewModel, domain_entity: GeneReview) -> None:
        db_model.rating = domain_entity.rating
        db_model.content = domain_entity.content
        db_model.deleted_at = domain_entity.deleted_at

    @override
    async def find_by_gene_id(
        self, gene_id: str, page: int, page_size: int
    ) -> tuple[list[GeneReview], int]:
        offset = (page - 1) * page_size

        # Base query with active reviews only
        base_query = (
            select(GeneReviewModel)
            .where(GeneReviewModel.gene_id == gene_id)
            .where(GeneReviewModel.deleted_at.is_(None))
        )

        # Count
        count_query = select(func.count()).select_from(base_query.subquery())
        count_result = await self._session.execute(count_query)
        total = count_result.scalar_one()

        # Fetch items
        items_query = (
            base_query.order_by(GeneReviewModel.created_at.desc()).offset(offset).limit(page_size)
        )
        items_result = await self._session.execute(items_query)
        items = [d for r in items_result.scalars().all() if (d := self._to_domain(r)) is not None]

        return items, total

    @override
    async def find_by_id(self, entity_id: str) -> GeneReview | None:
        query = (
            select(GeneReviewModel)
            .where(GeneReviewModel.id == entity_id)
            .where(GeneReviewModel.deleted_at.is_(None))
        )
        result = await self._session.execute(query)
        db_review = result.scalar_one_or_none()
        if db_review is None:
            return None
        return self._to_domain(db_review)

    @override
    async def save(self, domain_entity: GeneReview) -> GeneReview:
        query = select(GeneReviewModel).where(GeneReviewModel.id == domain_entity.id).limit(1)
        result = await self._session.execute(query)
        existing = result.scalar_one_or_none()
        if existing is not None:
            self._update_fields(existing, domain_entity)
        else:
            db_model = self._to_db(domain_entity)
            self._session.add(db_model)
        await self._session.flush()
        return domain_entity

    @override
    async def soft_delete(self, review_id: str, user_id: str) -> None:
        stmt = (
            update(GeneReviewModel)
            .where(GeneReviewModel.id == review_id)
            .where(GeneReviewModel.user_id == user_id)
            .where(GeneReviewModel.deleted_at.is_(None))
            .values(deleted_at=datetime.now(UTC))
        )
        await self._session.execute(stmt)
        await self._session.flush()
