"""SQLAlchemy implementation of GeneRatingRepository.

This repository does NOT extend BaseRepository since it handles two
separate ORM models (GeneRatingModel and GenomeRatingModel).
"""

import logging
from typing import override

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.instance_gene import GeneRating, GenomeRating
from src.domain.ports.repositories.gene_rating_repository import GeneRatingRepository
from src.infrastructure.adapters.secondary.persistence.models import (
    GeneRatingModel,
    GenomeRatingModel,
)

logger = logging.getLogger(__name__)


class SqlGeneRatingRepository(GeneRatingRepository):
    """SQLAlchemy implementation of GeneRatingRepository."""

    def __init__(self, session: AsyncSession) -> None:
        super().__init__()
        self._session = session

    @override
    async def save_gene_rating(self, rating: GeneRating) -> GeneRating:
        query = select(GeneRatingModel).where(GeneRatingModel.id == rating.id).limit(1)
        result = await self._session.execute(query)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.rating = rating.rating
            existing.comment = rating.comment
        else:
            db_model = GeneRatingModel(
                id=rating.id,
                gene_id=rating.gene_id,
                user_id=rating.user_id,
                rating=rating.rating,
                comment=rating.comment,
                created_at=rating.created_at,
            )
            self._session.add(db_model)
        await self._session.flush()
        return rating

    @override
    async def find_gene_ratings(
        self, gene_id: str, limit: int = 50, offset: int = 0
    ) -> list[GeneRating]:
        query = (
            select(GeneRatingModel)
            .where(GeneRatingModel.gene_id == gene_id)
            .order_by(GeneRatingModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        db_ratings = result.scalars().all()
        return [self._gene_rating_to_domain(r) for r in db_ratings]

    @override
    async def find_user_gene_rating(self, gene_id: str, user_id: str) -> GeneRating | None:
        query = (
            select(GeneRatingModel)
            .where(GeneRatingModel.gene_id == gene_id)
            .where(GeneRatingModel.user_id == user_id)
            .limit(1)
        )
        result = await self._session.execute(query)
        db_rating = result.scalar_one_or_none()
        if db_rating is None:
            return None
        return self._gene_rating_to_domain(db_rating)

    @override
    async def save_genome_rating(self, rating: GenomeRating) -> GenomeRating:
        query = select(GenomeRatingModel).where(GenomeRatingModel.id == rating.id).limit(1)
        result = await self._session.execute(query)
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.rating = rating.rating
            existing.comment = rating.comment
        else:
            db_model = GenomeRatingModel(
                id=rating.id,
                genome_id=rating.genome_id,
                user_id=rating.user_id,
                rating=rating.rating,
                comment=rating.comment,
                created_at=rating.created_at,
            )
            self._session.add(db_model)
        await self._session.flush()
        return rating

    @override
    async def find_genome_ratings(
        self, genome_id: str, limit: int = 50, offset: int = 0
    ) -> list[GenomeRating]:
        query = (
            select(GenomeRatingModel)
            .where(GenomeRatingModel.genome_id == genome_id)
            .order_by(GenomeRatingModel.created_at.desc())
            .offset(offset)
            .limit(limit)
        )
        result = await self._session.execute(query)
        db_ratings = result.scalars().all()
        return [self._genome_rating_to_domain(r) for r in db_ratings]

    @override
    async def find_user_genome_rating(self, genome_id: str, user_id: str) -> GenomeRating | None:
        query = (
            select(GenomeRatingModel)
            .where(GenomeRatingModel.genome_id == genome_id)
            .where(GenomeRatingModel.user_id == user_id)
            .limit(1)
        )
        result = await self._session.execute(query)
        db_rating = result.scalar_one_or_none()
        if db_rating is None:
            return None
        return self._genome_rating_to_domain(db_rating)

    @staticmethod
    def _gene_rating_to_domain(db_rating: GeneRatingModel) -> GeneRating:
        return GeneRating(
            id=db_rating.id,
            gene_id=db_rating.gene_id,
            user_id=db_rating.user_id,
            rating=db_rating.rating,
            comment=db_rating.comment,
            created_at=db_rating.created_at,
        )

    @staticmethod
    def _genome_rating_to_domain(db_rating: GenomeRatingModel) -> GenomeRating:
        return GenomeRating(
            id=db_rating.id,
            genome_id=db_rating.genome_id,
            user_id=db_rating.user_id,
            rating=db_rating.rating,
            comment=db_rating.comment,
            created_at=db_rating.created_at,
        )
