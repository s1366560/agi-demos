from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.gene.instance_gene import GeneRating, GenomeRating
from src.infrastructure.adapters.secondary.persistence.models import (
    GeneMarketModel,
    GenomeModel,
    Project,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_rating_repository import (
    SqlGeneRatingRepository,
)


@pytest.mark.unit
async def test_gene_rating_repository_calculates_gene_and_genome_averages(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    other_user = User(
        id="rating-user-2",
        email="rating-user-2@example.com",
        hashed_password="hashed",
    )
    test_db.add(other_user)
    test_db.add_all(
        [
            GeneMarketModel(
                id="rated-gene",
                name="Rated Gene",
                slug="rated-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                category="target",
                is_published=True,
            ),
            GenomeModel(
                id="rated-genome",
                name="Rated Genome",
                slug="rated-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                gene_slugs=[],
                is_published=True,
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneRatingRepository(test_db)

    assert await repo.get_gene_average_rating("rated-gene") == 0.0
    assert await repo.get_genome_average_rating("rated-genome") == 0.0

    await repo.save_gene_rating(GeneRating(gene_id="rated-gene", user_id=test_user.id, rating=5))
    await repo.save_gene_rating(GeneRating(gene_id="rated-gene", user_id=other_user.id, rating=3))
    await repo.save_genome_rating(
        GenomeRating(genome_id="rated-genome", user_id=test_user.id, rating=2)
    )
    await repo.save_genome_rating(
        GenomeRating(genome_id="rated-genome", user_id=other_user.id, rating=5)
    )

    assert await repo.get_gene_average_rating("rated-gene") == 4.0
    assert await repo.get_genome_average_rating("rated-genome") == 3.5
