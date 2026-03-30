"""Repository interface for Genome entity."""

from abc import ABC, abstractmethod

from src.domain.model.gene.gene import Genome


class GenomeRepository(ABC):
    """Repository interface for Genome entity."""

    @abstractmethod
    async def save(self, domain_entity: Genome) -> Genome:
        """Save a genome (create or update). Returns the saved genome."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> Genome | None:
        """Find a genome by ID."""

    @abstractmethod
    async def find_by_slug(self, slug: str) -> Genome | None:
        """Find a genome by slug."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Genome]:
        """List all genomes in a tenant."""

    @abstractmethod
    async def find_featured(self, limit: int = 20) -> list[Genome]:
        """List featured genomes."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a genome. Returns True if deleted, False if not found."""
