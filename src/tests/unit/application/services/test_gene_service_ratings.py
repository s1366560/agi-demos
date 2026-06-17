from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.models import Project, User


@pytest.mark.unit
async def test_rate_gene_updates_persisted_average_rating(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    gene = await service.create_gene(
        name="Rated Gene",
        slug="rated-gene",
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    await service.rate_gene(gene.id, test_user.id, 5)
    refreshed_gene = await service.get_gene(gene.id)

    assert refreshed_gene is not None
    assert refreshed_gene.avg_rating == 5.0

    await service.rate_gene(gene.id, test_user.id, 3)
    refreshed_gene = await service.get_gene(gene.id)

    assert refreshed_gene is not None
    assert refreshed_gene.avg_rating == 3.0


@pytest.mark.unit
async def test_rate_genome_updates_persisted_average_rating(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Rated Genome",
        slug="rated-genome",
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    await service.rate_genome(genome.id, test_user.id, 4)
    refreshed_genome = await service.get_genome(genome.id)

    assert refreshed_genome is not None
    assert refreshed_genome.avg_rating == 4.0

    await service.rate_genome(genome.id, test_user.id, 2)
    refreshed_genome = await service.get_genome(genome.id)

    assert refreshed_genome is not None
    assert refreshed_genome.avg_rating == 2.0
