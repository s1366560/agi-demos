"""Repository interface for DeployRecord entity."""

from abc import ABC, abstractmethod

from src.domain.model.deploy.deploy_record import DeployRecord


class DeployRecordRepository(ABC):
    """Repository interface for DeployRecord entity."""

    @abstractmethod
    async def save(self, domain_entity: DeployRecord) -> DeployRecord:
        """Save a deploy record (create or update). Returns the saved record."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> DeployRecord | None:
        """Find a deploy record by ID."""

    @abstractmethod
    async def find_by_instance(
        self, instance_id: str, limit: int = 50, offset: int = 0
    ) -> list[DeployRecord]:
        """List deploy records for an instance."""

    @abstractmethod
    async def find_latest_by_instance(self, instance_id: str) -> DeployRecord | None:
        """Find the latest deploy record for an instance."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a deploy record. Returns True if deleted, False if not found."""
