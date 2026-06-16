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
