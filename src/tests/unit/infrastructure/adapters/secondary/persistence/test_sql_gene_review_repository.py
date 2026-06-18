from __future__ import annotations

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import (
    GeneMarketModel,
    GeneReviewModel,
    Project,
    User,
)
from src.infrastructure.adapters.secondary.persistence.sql_gene_review_repository import (
    SqlGeneReviewRepository,
)


@pytest.mark.unit
async def test_gene_review_repository_filters_and_deletes_by_tenant(
    test_db: AsyncSession,
    test_project_db: Project,
    test_user: User,
) -> None:
    tenant_id = test_project_db.tenant_id
    test_db.add(
        GeneMarketModel(
            id="global-gene-review-target",
            name="Global Gene Review Target",
            slug="global-gene-review-target",
            tenant_id=None,
            created_by=test_user.id,
            category="target",
            is_published=True,
        )
    )
    test_db.add_all(
        [
            GeneReviewModel(
                id="tenant-review",
                gene_id="global-gene-review-target",
                tenant_id=tenant_id,
                user_id=test_user.id,
                rating=5,
                content="Tenant scoped review",
            ),
            GeneReviewModel(
                id="legacy-global-review",
                gene_id="global-gene-review-target",
                tenant_id=None,
                user_id=test_user.id,
                rating=1,
                content="Legacy global review",
            ),
        ]
    )
    await test_db.flush()

    repo = SqlGeneReviewRepository(test_db)

    reviews, total = await repo.find_by_gene_id("global-gene-review-target", tenant_id, 1, 10)

    assert total == 1
    assert [review.id for review in reviews] == ["tenant-review"]
    assert await repo.find_by_id("legacy-global-review", tenant_id) is None

    await repo.soft_delete("legacy-global-review", test_user.id, tenant_id)
    legacy_review = await test_db.scalar(
        select(GeneReviewModel).where(GeneReviewModel.id == "legacy-global-review")
    )
    assert legacy_review is not None
    assert legacy_review.deleted_at is None

    await repo.soft_delete("tenant-review", test_user.id, tenant_id)
    tenant_review = await test_db.scalar(
        select(GeneReviewModel).where(GeneReviewModel.id == "tenant-review")
    )
    assert tenant_review is not None
    assert tenant_review.deleted_at is not None
