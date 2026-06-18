from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.services.gene_service import GeneService
from src.domain.model.gene.enums import ContentVisibility
from src.domain.model.gene.gene import Gene
from src.domain.model.gene.instance_gene import GeneReview


def _gene(
    *,
    gene_id: str = "gene-1",
    tenant_id: str | None = "tenant-1",
    is_published: bool = True,
    visibility: ContentVisibility = ContentVisibility.public,
) -> Gene:
    return Gene(
        id=gene_id,
        name="Test Gene",
        slug="test-gene",
        tenant_id=tenant_id,
        is_published=is_published,
        visibility=visibility,
    )


def _service_with_review_repo(
    gene_review_repo: AsyncMock,
    *,
    gene: Gene | None = None,
) -> GeneService:
    gene_repo = AsyncMock()
    gene_repo.find_by_id.return_value = gene if gene is not None else _gene()
    return GeneService(
        gene_repo=gene_repo,
        genome_repo=AsyncMock(),
        instance_gene_repo=AsyncMock(),
        gene_rating_repo=AsyncMock(),
        evolution_event_repo=AsyncMock(),
        gene_review_repo=gene_review_repo,
    )


@pytest.mark.unit
async def test_delete_gene_review_rejects_review_for_different_gene() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.find_by_id.return_value = GeneReview(
        id="review-1",
        gene_id="other-gene",
        user_id="user-1",
        tenant_id="tenant-1",
        rating=5,
        content="Useful",
    )
    service = _service_with_review_repo(gene_review_repo)

    with pytest.raises(ValueError, match="Review review-1 not found"):
        await service.delete_gene_review(
            gene_id="gene-1",
            review_id="review-1",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    gene_review_repo.soft_delete.assert_not_awaited()
    gene_review_repo.find_by_id.assert_awaited_once_with("review-1", "tenant-1")


@pytest.mark.unit
async def test_delete_gene_review_soft_deletes_matching_user_review() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.find_by_id.return_value = GeneReview(
        id="review-1",
        gene_id="gene-1",
        user_id="user-1",
        tenant_id="tenant-1",
        rating=5,
        content="Useful",
    )
    service = _service_with_review_repo(gene_review_repo)

    await service.delete_gene_review(
        gene_id="gene-1",
        review_id="review-1",
        user_id="user-1",
        tenant_id="tenant-1",
    )

    gene_review_repo.find_by_id.assert_awaited_once_with("review-1", "tenant-1")
    gene_review_repo.soft_delete.assert_awaited_once_with("review-1", "user-1", "tenant-1")


@pytest.mark.unit
async def test_create_gene_review_rejects_gene_outside_tenant() -> None:
    gene_review_repo = AsyncMock()
    service = _service_with_review_repo(
        gene_review_repo,
        gene=_gene(tenant_id="tenant-2"),
    )

    with pytest.raises(ValueError, match="Gene gene-1 not found"):
        await service.create_gene_review(
            gene_id="gene-1",
            user_id="user-1",
            rating=5,
            content="Useful",
            tenant_id="tenant-1",
        )

    gene_review_repo.save.assert_not_awaited()


@pytest.mark.unit
async def test_create_gene_review_persists_tenant_scope() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.save.side_effect = lambda review: review
    service = _service_with_review_repo(gene_review_repo)

    review = await service.create_gene_review(
        gene_id="gene-1",
        user_id="user-1",
        rating=5,
        content="Useful",
        tenant_id="tenant-1",
    )

    assert review.tenant_id == "tenant-1"
    saved_review = gene_review_repo.save.await_args.args[0]
    assert saved_review.tenant_id == "tenant-1"


@pytest.mark.unit
async def test_list_gene_reviews_allows_published_public_global_gene() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.find_by_gene_id.return_value = ([], 0)
    service = _service_with_review_repo(
        gene_review_repo,
        gene=_gene(tenant_id=None, is_published=True, visibility=ContentVisibility.public),
    )

    reviews, total = await service.list_gene_reviews(
        gene_id="gene-1",
        page=1,
        page_size=10,
        tenant_id="tenant-1",
    )

    assert reviews == []
    assert total == 0
    gene_review_repo.find_by_gene_id.assert_awaited_once_with("gene-1", "tenant-1", 1, 10)


@pytest.mark.unit
async def test_delete_gene_review_rejects_unpublished_global_gene() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.find_by_id.return_value = GeneReview(
        id="review-1",
        gene_id="gene-1",
        user_id="user-1",
        tenant_id="tenant-1",
        rating=5,
        content="Useful",
    )
    service = _service_with_review_repo(
        gene_review_repo,
        gene=_gene(tenant_id=None, is_published=False, visibility=ContentVisibility.public),
    )

    with pytest.raises(ValueError, match="Gene gene-1 not found"):
        await service.delete_gene_review(
            gene_id="gene-1",
            review_id="review-1",
            user_id="user-1",
            tenant_id="tenant-1",
        )

    gene_review_repo.find_by_id.assert_not_awaited()
    gene_review_repo.soft_delete.assert_not_awaited()
