from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.gene.instance_gene import GeneReview


class GeneReviewRepository(ABC):
    @abstractmethod
    async def find_by_gene_id(
        self, gene_id: str, page: int, page_size: int
    ) -> tuple[list[GeneReview], int]:
        """List active reviews for a gene, paginated, and return total count."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> GeneReview | None:
        """Find a review by ID."""

    @abstractmethod
    async def save(self, domain_entity: GeneReview) -> GeneReview:
        """Save a gene review (create or update). Returns the saved review."""

    @abstractmethod
    async def soft_delete(self, review_id: str, user_id: str) -> None:
        """Soft-delete a review by setting deleted_at."""
