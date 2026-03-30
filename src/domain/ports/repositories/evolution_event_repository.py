"""Repository interface for EvolutionEvent entity."""

from abc import ABC, abstractmethod

from src.domain.model.gene.instance_gene import EvolutionEvent


class EvolutionEventRepository(ABC):
    """Repository interface for EvolutionEvent entity."""

    @abstractmethod
    async def save(self, domain_entity: EvolutionEvent) -> EvolutionEvent:
        """Save an evolution event. Returns the saved event."""

    @abstractmethod
    async def find_by_instance(
        self, instance_id: str, limit: int = 100, offset: int = 0
    ) -> list[EvolutionEvent]:
        """List evolution events for an instance."""

    @abstractmethod
    async def find_by_gene(
        self, gene_id: str, limit: int = 100, offset: int = 0
    ) -> list[EvolutionEvent]:
        """List evolution events for a gene."""
