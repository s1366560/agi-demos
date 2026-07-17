"""Repository interface for the GraphStore entity."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.graph_store.graph_store import GraphStore


class GraphStoreRepository(ABC):
    """Repository interface for graph backend registrations."""

    @abstractmethod
    async def save(self, entity: GraphStore) -> GraphStore:
        """Save a graph store (create or update). Returns the saved entity."""

    @abstractmethod
    async def find_by_id(self, tenant_id: str, store_id: str) -> GraphStore | None:
        """Find a non-deleted graph store by id, scoped to the tenant."""

    async def find_by_ids(self, tenant_id: str, store_ids: list[str]) -> dict[str, GraphStore]:
        """Find multiple non-deleted graph stores by id, keyed by store id.

        The default implementation issues one query per id; backends should
        override it with a single IN query to avoid N+1 reads.
        """
        stores: dict[str, GraphStore] = {}
        for store_id in dict.fromkeys(store_ids):
            store = await self.find_by_id(tenant_id, store_id)
            if store is not None:
                stores[store_id] = store
        return stores

    @abstractmethod
    async def find_by_name(self, tenant_id: str, name: str) -> GraphStore | None:
        """Find a non-deleted graph store by tenant + name."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[GraphStore]:
        """List non-deleted graph stores for a tenant."""

    @abstractmethod
    async def count_projects_bound(self, store_id: str) -> int:
        """Count non-deleted projects bound to a graph store (delete protection)."""

    @abstractmethod
    async def soft_delete(self, tenant_id: str, store_id: str) -> bool:
        """Soft-delete a graph store. Returns True if deleted, False if not found."""
