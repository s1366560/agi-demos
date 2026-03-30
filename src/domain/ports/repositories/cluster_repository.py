"""Repository interface for Cluster entity."""

from abc import ABC, abstractmethod

from src.domain.model.cluster.cluster import Cluster


class ClusterRepository(ABC):
    """Repository interface for Cluster entity."""

    @abstractmethod
    async def save(self, domain_entity: Cluster) -> Cluster:
        """Save a cluster (create or update). Returns the saved cluster."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> Cluster | None:
        """Find a cluster by ID."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[Cluster]:
        """List all clusters in a tenant."""

    @abstractmethod
    async def find_by_name(self, tenant_id: str, name: str) -> Cluster | None:
        """Find a cluster by tenant and name."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a cluster. Returns True if deleted, False if not found."""
