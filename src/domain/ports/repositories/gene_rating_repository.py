"""Repository interface for GeneRating and GenomeRating entities."""

from abc import ABC, abstractmethod

from src.domain.model.gene.instance_gene import GeneRating, GenomeRating


class GeneRatingRepository(ABC):
    """Repository interface for GeneRating and GenomeRating entities."""

    @abstractmethod
    async def save_gene_rating(self, rating: GeneRating) -> GeneRating:
        """Save a gene rating (create or update). Returns the saved rating."""

    @abstractmethod
    async def find_gene_ratings(
        self, gene_id: str, limit: int = 50, offset: int = 0
    ) -> list[GeneRating]:
        """List ratings for a gene."""

    @abstractmethod
    async def find_user_gene_rating(self, gene_id: str, user_id: str) -> GeneRating | None:
        """Find a specific user's rating for a gene."""

    @abstractmethod
    async def save_genome_rating(self, rating: GenomeRating) -> GenomeRating:
        """Save a genome rating (create or update). Returns the saved rating."""

    @abstractmethod
    async def find_genome_ratings(
        self, genome_id: str, limit: int = 50, offset: int = 0
    ) -> list[GenomeRating]:
        """List ratings for a genome."""

    @abstractmethod
    async def find_user_genome_rating(self, genome_id: str, user_id: str) -> GenomeRating | None:
        """Find a specific user's rating for a genome."""
