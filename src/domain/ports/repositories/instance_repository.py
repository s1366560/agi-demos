"""Repository interface for Instance entity."""

from abc import ABC, abstractmethod

from src.domain.model.instance.instance import Instance


class InstanceRepository(ABC):
    """Repository interface for Instance entity."""

    @abstractmethod
    async def save(self, domain_entity: Instance) -> Instance:
        """Save an instance (create or update). Returns the saved instance."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> Instance | None:
        """Find an instance by ID."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Instance]:
        """List all instances in a tenant."""

    @abstractmethod
    async def find_by_slug(self, tenant_id: str, slug: str) -> Instance | None:
        """Find an instance by tenant and slug."""

    @abstractmethod
    async def find_by_workspace(self, workspace_id: str) -> list[Instance]:
        """List all instances in a workspace."""

    @abstractmethod
    async def find_by_cluster(self, cluster_id: str) -> list[Instance]:
        """List all instances deployed to a cluster."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete an instance. Returns True if deleted, False if not found."""
