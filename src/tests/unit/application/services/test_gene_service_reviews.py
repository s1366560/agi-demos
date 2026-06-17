from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.application.services.gene_service import GeneService
from src.domain.model.gene.instance_gene import GeneReview


def _service_with_review_repo(gene_review_repo: AsyncMock) -> GeneService:
    return GeneService(
        gene_repo=AsyncMock(),
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


@pytest.mark.unit
async def test_delete_gene_review_soft_deletes_matching_user_review() -> None:
    gene_review_repo = AsyncMock()
    gene_review_repo.find_by_id.return_value = GeneReview(
        id="review-1",
        gene_id="gene-1",
        user_id="user-1",
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

    gene_review_repo.soft_delete.assert_awaited_once_with("review-1", "user-1")
