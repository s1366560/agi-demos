from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from src.configuration.di_container import DIContainer
from src.infrastructure.adapters.secondary.persistence.models import Project, User


def _slug(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.mark.unit
async def test_create_gene_rejects_duplicate_slug(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("duplicate-gene")

    await service.create_gene(
        name="Original Gene",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    with pytest.raises(ValueError, match="Gene slug already exists"):
        await service.create_gene(
            name="Duplicate Gene",
            slug=slug,
            created_by=test_user.id,
            tenant_id=test_project_db.tenant_id,
        )


@pytest.mark.unit
async def test_create_gene_allows_duplicate_slug_in_different_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("shared-gene")

    first = await service.create_gene(
        name="First Tenant Gene",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    second = await service.create_gene(
        name="Second Tenant Gene",
        slug=slug,
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    assert first.slug == second.slug
    assert first.tenant_id != second.tenant_id


@pytest.mark.unit
async def test_create_gene_persists_source_metadata(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    gene = await service.create_gene(
        name="Imported Gene",
        slug=_slug("imported-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        source_ref="github:org/repo/path",
        parent_gene_id="parent-gene-1",
    )
    reloaded = await service.get_gene(gene.id)

    assert reloaded is not None
    assert reloaded.source_ref == "github:org/repo/path"
    assert reloaded.parent_gene_id == "parent-gene-1"


@pytest.mark.unit
async def test_create_gene_accepts_unlisted_visibility(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()

    gene = await service.create_gene(
        name="Unlisted Gene",
        slug=_slug("unlisted-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        visibility="unlisted",
    )
    reloaded = await service.get_gene(gene.id)

    assert reloaded is not None
    assert reloaded.visibility.value == "unlisted"


@pytest.mark.unit
async def test_update_gene_applies_slug_and_metadata_fields(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    gene = await service.create_gene(
        name="Original Gene",
        slug=_slug("original-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    new_slug = _slug("updated-gene")

    updated = await service.update_gene(
        gene.id,
        slug=new_slug,
        source_ref="registry:updated",
        parent_gene_id="parent-gene-2",
    )

    assert updated.slug == new_slug
    assert updated.source_ref == "registry:updated"
    assert updated.parent_gene_id == "parent-gene-2"


@pytest.mark.unit
async def test_update_gene_normalizes_nullable_collection_fields(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    gene = await service.create_gene(
        name="Configurable Gene",
        slug=_slug("configurable-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        tags=["review"],
        manifest={"mode": "strict"},
        dependencies=["base-gene"],
        synergies=["helper-gene"],
    )

    updated = await service.update_gene(
        gene.id,
        tags=None,
        manifest=None,
        dependencies=None,
        synergies=None,
    )

    assert updated.tags == []
    assert updated.manifest == {}
    assert updated.dependencies == []
    assert updated.synergies == []


@pytest.mark.unit
async def test_update_gene_rejects_duplicate_slug(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("existing-gene")
    await service.create_gene(
        name="Existing Gene",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    gene = await service.create_gene(
        name="Editable Gene",
        slug=_slug("editable-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    with pytest.raises(ValueError, match="Gene slug already exists"):
        await service.update_gene(gene.id, slug=slug)


@pytest.mark.unit
async def test_update_gene_allows_duplicate_slug_in_different_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("shared-update-gene")
    await service.create_gene(
        name="Existing Gene",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    gene = await service.create_gene(
        name="Editable Other Tenant Gene",
        slug=_slug("editable-other-gene"),
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    updated = await service.update_gene(gene.id, slug=slug)

    assert updated.slug == slug
    assert updated.tenant_id == "other-tenant"


@pytest.mark.unit
async def test_create_genome_rejects_duplicate_slug(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("duplicate-genome")

    await service.create_genome(
        name="Original Genome",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    with pytest.raises(ValueError, match="Genome slug already exists"):
        await service.create_genome(
            name="Duplicate Genome",
            slug=slug,
            created_by=test_user.id,
            tenant_id=test_project_db.tenant_id,
        )


@pytest.mark.unit
async def test_create_genome_allows_duplicate_slug_in_different_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("shared-genome")

    first = await service.create_genome(
        name="First Tenant Genome",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    second = await service.create_genome(
        name="Second Tenant Genome",
        slug=slug,
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    assert first.slug == second.slug
    assert first.tenant_id != second.tenant_id


@pytest.mark.unit
async def test_create_genome_normalizes_gene_slugs(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    gene = await service.create_gene(
        name="Genome Gene",
        slug=_slug("genome-gene"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    genome = await service.create_genome(
        name="Normalized Genome",
        slug=_slug("normalized-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        gene_slugs=[f" {gene.slug} ", gene.slug, ""],
    )

    assert genome.gene_slugs == [gene.slug]


@pytest.mark.unit
async def test_create_genome_allows_published_global_gene_slugs(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    global_gene = await service.create_gene(
        name="Global Genome Gene",
        slug=_slug("global-genome-gene"),
        created_by=test_user.id,
        tenant_id=None,
    )
    global_gene = await service.publish_gene(global_gene.id)

    genome = await service.create_genome(
        name="Global Slug Genome",
        slug=_slug("global-slug-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        gene_slugs=[global_gene.slug],
    )

    assert genome.gene_slugs == [global_gene.slug]


@pytest.mark.unit
async def test_create_genome_rejects_missing_or_foreign_gene_slugs(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    foreign_gene = await service.create_gene(
        name="Foreign Gene",
        slug=_slug("foreign-gene"),
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    with pytest.raises(ValueError, match="Genome gene slugs not found"):
        await service.create_genome(
            name="Invalid Genome",
            slug=_slug("invalid-genome"),
            created_by=test_user.id,
            tenant_id=test_project_db.tenant_id,
            gene_slugs=[foreign_gene.slug, _slug("missing-gene")],
        )


@pytest.mark.unit
async def test_update_genome_applies_slug(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Original Genome",
        slug=_slug("original-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    new_slug = _slug("updated-genome")

    updated = await service.update_genome(genome.id, slug=new_slug)

    assert updated.slug == new_slug


@pytest.mark.unit
async def test_update_genome_accepts_unlisted_visibility(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Visibility Genome",
        slug=_slug("visibility-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    updated = await service.update_genome(genome.id, visibility="unlisted")

    assert updated.visibility.value == "unlisted"


@pytest.mark.unit
async def test_update_genome_normalizes_nullable_config_override(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Configurable Genome",
        slug=_slug("configurable-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
        config_override={"mode": "strict"},
    )

    updated = await service.update_genome(genome.id, config_override=None)

    assert updated.config_override == {}


@pytest.mark.unit
async def test_update_genome_rejects_duplicate_slug(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("existing-genome")
    await service.create_genome(
        name="Existing Genome",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    genome = await service.create_genome(
        name="Editable Genome",
        slug=_slug("editable-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )

    with pytest.raises(ValueError, match="Genome slug already exists"):
        await service.update_genome(genome.id, slug=slug)


@pytest.mark.unit
async def test_update_genome_allows_duplicate_slug_in_different_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    slug = _slug("shared-update-genome")
    await service.create_genome(
        name="Existing Genome",
        slug=slug,
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    genome = await service.create_genome(
        name="Editable Other Tenant Genome",
        slug=_slug("editable-other-genome"),
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    updated = await service.update_genome(genome.id, slug=slug)

    assert updated.slug == slug
    assert updated.tenant_id == "other-tenant"


@pytest.mark.unit
async def test_update_genome_rejects_missing_or_foreign_gene_slugs(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    service = DIContainer().with_db(test_db).gene_service()
    genome = await service.create_genome(
        name="Editable Genome",
        slug=_slug("editable-genome"),
        created_by=test_user.id,
        tenant_id=test_project_db.tenant_id,
    )
    foreign_gene = await service.create_gene(
        name="Foreign Gene",
        slug=_slug("foreign-gene"),
        created_by=test_user.id,
        tenant_id="other-tenant",
    )

    with pytest.raises(ValueError, match="Genome gene slugs not found"):
        await service.update_genome(genome.id, gene_slugs=[foreign_gene.slug])
