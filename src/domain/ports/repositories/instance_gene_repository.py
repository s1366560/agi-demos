"""Repository interface for InstanceGene and GeneEffectLog entities."""

from abc import ABC, abstractmethod

from src.domain.model.gene.instance_gene import GeneEffectLog, InstanceGene


class InstanceGeneRepository(ABC):
    """Repository interface for InstanceGene entity."""

    @abstractmethod
    async def save(self, domain_entity: InstanceGene) -> InstanceGene:
        """Save an instance gene (create or update). Returns the saved instance gene."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> InstanceGene | None:
        """Find an instance gene by ID."""

    @abstractmethod
    async def find_by_instance(self, instance_id: str) -> list[InstanceGene]:
        """List all genes installed on an instance."""

    @abstractmethod
    async def find_by_gene(self, gene_id: str) -> list[InstanceGene]:
        """List all instances that have a specific gene installed."""

    @abstractmethod
    async def find_by_instance_and_gene(
        self, instance_id: str, gene_id: str
    ) -> InstanceGene | None:
        """Find an instance gene by instance ID and gene ID."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete an instance gene. Returns True if deleted, False if not found."""

    @abstractmethod
    async def save_effect_log(self, log: GeneEffectLog) -> GeneEffectLog:
        """Save a gene effect log entry."""

    @abstractmethod
    async def find_effect_logs(
        self, instance_id: str, gene_id: str, limit: int = 100
    ) -> list[GeneEffectLog]:
        """Find effect logs for a gene on an instance."""
