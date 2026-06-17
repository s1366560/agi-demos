from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    GeneMarketModel,
    GenomeModel,
    Project,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_repository import (
    SqlGeneRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_genome_repository import (
    SqlGenomeRepository,
)


def _gene(
    *,
    gene_id: str,
    slug: str,
    tenant_id: str,
    created_by: str,
    name: str,
    category: str = "target",
    is_featured: bool = False,
    is_published: bool = True,
    deleted_at: datetime | None = None,
) -> GeneMarketModel:
    return GeneMarketModel(
        id=gene_id,
        name=name,
        slug=slug,
        tenant_id=tenant_id,
        created_by=created_by,
        category=category,
        description="Needle repository listing candidate",
        short_description="Needle",
        is_featured=is_featured,
        is_published=is_published,
        deleted_at=deleted_at,
    )


def _genome(
    *,
    genome_id: str,
    slug: str,
    tenant_id: str,
    created_by: str,
    name: str,
    is_featured: bool = False,
    is_published: bool = True,
    deleted_at: datetime | None = None,
) -> GenomeModel:
    return GenomeModel(
        id=genome_id,
        name=name,
        slug=slug,
        tenant_id=tenant_id,
        created_by=created_by,
        short_description="Needle",
        gene_slugs=[],
        is_featured=is_featured,
        is_published=is_published,
        deleted_at=deleted_at,
    )


@pytest.mark.unit
async def test_gene_repository_lists_and_counts_only_active_rows(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    deleted_at = datetime.now(UTC)
    test_db.add_all(
        [
            _gene(
                gene_id="active-gene",
                slug="active-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Active Gene",
                is_featured=True,
            ),
            _gene(
                gene_id="deleted-gene",
                slug="deleted-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Deleted Gene",
                is_featured=True,
                deleted_at=deleted_at,
            ),
            _gene(
                gene_id="other-category-gene",
                slug="other-category-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Other Gene",
                category="other",
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneRepository(test_db)

    tenant_genes = await repo.find_by_tenant(test_project_db.tenant_id, limit=10, offset=0)
    filtered_genes = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        category="target",
        search="Needle",
        is_published=True,
        limit=10,
        offset=0,
    )
    filtered_total = await repo.count_by_filters(
        tenant_id=test_project_db.tenant_id,
        category="target",
        search="Needle",
        is_published=True,
    )
    search_results = await repo.search("Needle", category="target", limit=10, offset=0)
    featured = await repo.find_featured(limit=10)
    deleted_detail = await repo.find_by_id("deleted-gene")

    assert {gene.id for gene in tenant_genes} == {"active-gene", "other-category-gene"}
    assert [gene.id for gene in filtered_genes] == ["active-gene"]
    assert filtered_total == 1
    assert [gene.id for gene in search_results] == ["active-gene"]
    assert [gene.id for gene in featured] == ["active-gene"]
    assert deleted_detail is None


@pytest.mark.unit
async def test_genome_repository_lists_and_counts_only_active_rows(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    deleted_at = datetime.now(UTC)
    test_db.add_all(
        [
            _genome(
                genome_id="active-genome",
                slug="active-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Active Genome",
                is_featured=True,
            ),
            _genome(
                genome_id="deleted-genome",
                slug="deleted-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Deleted Genome",
                is_featured=True,
                deleted_at=deleted_at,
            ),
            _genome(
                genome_id="draft-genome",
                slug="draft-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Draft Genome",
                is_published=False,
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGenomeRepository(test_db)

    tenant_genomes = await repo.find_by_tenant(test_project_db.tenant_id, limit=10, offset=0)
    published_genomes = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=10,
        offset=0,
    )
    published_total = await repo.count_by_filters(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
    )
    featured = await repo.find_featured(limit=10)
    deleted_detail = await repo.find_by_id("deleted-genome")

    assert {genome.id for genome in tenant_genomes} == {"active-genome", "draft-genome"}
    assert [genome.id for genome in published_genomes] == ["active-genome"]
    assert published_total == 1
    assert [genome.id for genome in featured] == ["active-genome"]
    assert deleted_detail is None
