from __future__ import annotations

from datetime import UTC, datetime, timedelta

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
    tenant_id: str | None,
    created_by: str,
    name: str,
    category: str = "target",
    is_featured: bool = False,
    is_published: bool = True,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> GeneMarketModel:
    model = GeneMarketModel(
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
    if created_at is not None:
        model.created_at = created_at
    return model


def _genome(
    *,
    genome_id: str,
    slug: str,
    tenant_id: str,
    created_by: str,
    name: str,
    is_featured: bool = False,
    is_published: bool = True,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> GenomeModel:
    model = GenomeModel(
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
    if created_at is not None:
        model.created_at = created_at
    return model


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
async def test_gene_repository_defaults_to_global_scope_when_tenant_id_is_omitted(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    test_db.add_all(
        [
            _gene(
                gene_id="tenant-gene",
                slug="tenant-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Tenant Gene",
                created_at=created_at + timedelta(minutes=1),
            ),
            _gene(
                gene_id="global-gene",
                slug="global-gene",
                tenant_id=None,
                created_by=test_user.id,
                name="Global Gene",
                created_at=created_at,
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneRepository(test_db)

    listed = await repo.find_by_filters(is_published=True, limit=10, offset=0)
    total = await repo.count_by_filters(is_published=True)

    assert [gene.id for gene in listed] == ["global-gene"]
    assert total == 1


@pytest.mark.unit
async def test_gene_repository_filters_and_counts_by_exact_slugs_before_pagination(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    test_db.add_all(
        [
            _gene(
                gene_id="matching-one",
                slug="matching-one",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Matching One",
            ),
            _gene(
                gene_id="matching-two",
                slug="matching-two",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Matching Two",
            ),
            _gene(
                gene_id="other-gene",
                slug="other-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Other Gene",
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneRepository(test_db)

    page = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        slugs=["matching-one", "matching-two"],
        limit=1,
        offset=0,
    )
    total = await repo.count_by_filters(
        tenant_id=test_project_db.tenant_id,
        slugs=["matching-one", "matching-two"],
    )

    assert total == 2
    assert len(page) == 1
    assert page[0].slug in {"matching-one", "matching-two"}


@pytest.mark.unit
async def test_gene_repository_orders_listings_newest_first_with_id_tiebreaker(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    test_db.add_all(
        [
            _gene(
                gene_id="tie-b-gene",
                slug="tie-b-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Tie B Gene",
                is_featured=True,
                created_at=created_at + timedelta(minutes=1),
            ),
            _gene(
                gene_id="older-gene",
                slug="older-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Older Gene",
                is_featured=True,
                created_at=created_at,
            ),
            _gene(
                gene_id="newest-gene",
                slug="newest-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Newest Gene",
                is_featured=True,
                created_at=created_at + timedelta(minutes=2),
            ),
            _gene(
                gene_id="tie-a-gene",
                slug="tie-a-gene",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Needle Tie A Gene",
                is_featured=True,
                created_at=created_at + timedelta(minutes=1),
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneRepository(test_db)

    listed = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        category="target",
        search="Needle",
        is_published=True,
        limit=4,
        offset=0,
    )
    second_page = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        category="target",
        search="Needle",
        is_published=True,
        limit=2,
        offset=2,
    )
    searched = await repo.search("Needle", category="target", limit=4, offset=0)
    featured = await repo.find_featured(limit=4)

    assert [gene.id for gene in listed] == [
        "newest-gene",
        "tie-a-gene",
        "tie-b-gene",
        "older-gene",
    ]
    assert [gene.id for gene in second_page] == ["tie-b-gene", "older-gene"]
    assert [gene.id for gene in searched] == [
        "newest-gene",
        "tie-a-gene",
        "tie-b-gene",
        "older-gene",
    ]
    assert [gene.id for gene in featured] == [
        "newest-gene",
        "tie-a-gene",
        "tie-b-gene",
        "older-gene",
    ]


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


@pytest.mark.unit
async def test_genome_repository_orders_listings_newest_first_with_id_tiebreaker(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    created_at = datetime(2026, 1, 1, tzinfo=UTC)
    test_db.add_all(
        [
            _genome(
                genome_id="tie-b-genome",
                slug="tie-b-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Tie B Genome",
                is_featured=True,
                created_at=created_at + timedelta(minutes=1),
            ),
            _genome(
                genome_id="older-genome",
                slug="older-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Older Genome",
                is_featured=True,
                created_at=created_at,
            ),
            _genome(
                genome_id="newest-genome",
                slug="newest-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Newest Genome",
                is_featured=True,
                created_at=created_at + timedelta(minutes=2),
            ),
            _genome(
                genome_id="tie-a-genome",
                slug="tie-a-genome",
                tenant_id=test_project_db.tenant_id,
                created_by=test_user.id,
                name="Tie A Genome",
                is_featured=True,
                created_at=created_at + timedelta(minutes=1),
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGenomeRepository(test_db)

    listed = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=4,
        offset=0,
    )
    second_page = await repo.find_by_filters(
        tenant_id=test_project_db.tenant_id,
        is_published=True,
        limit=2,
        offset=2,
    )
    featured = await repo.find_featured(limit=4)

    assert [genome.id for genome in listed] == [
        "newest-genome",
        "tie-a-genome",
        "tie-b-genome",
        "older-genome",
    ]
    assert [genome.id for genome in second_page] == ["tie-b-genome", "older-genome"]
    assert [genome.id for genome in featured] == [
        "newest-genome",
        "tie-a-genome",
        "tie-b-genome",
        "older-genome",
    ]
