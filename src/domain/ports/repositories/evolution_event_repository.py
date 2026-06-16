"""Repository interface for EvolutionEvent entity."""

from abc import ABC, abstractmethod

from src.domain.model.gene.enums import EvolutionEventType
from src.domain.model.gene.instance_gene import EvolutionEvent


class EvolutionEventRepository(ABC):
    """Repository interface for EvolutionEvent entity."""

    @abstractmethod
    async def save(self, domain_entity: EvolutionEvent) -> EvolutionEvent:
        """Save an evolution event. Returns the saved event."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> EvolutionEvent | None:
        """Find an evolution event by ID."""

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

    async def find_by_filters(
        self,
        *,
        instance_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[EvolutionEvent]:
        """List evolution events with filters applied before pagination."""
        raise NotImplementedError

    async def count_by_filters(
        self,
        *,
        instance_id: str | None = None,
        gene_id: str | None = None,
        event_type: EvolutionEventType | str | None = None,
    ) -> int:
        """Count evolution events matching the same filters used for listing."""
        raise NotImplementedError
