"""Repository interface for RetrievalStore."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.retrieval_store import RetrievalStore


class RetrievalStoreRepository(ABC):
    """Repository interface for retrieval backend registrations."""

    @abstractmethod
    async def save(self, entity: RetrievalStore) -> RetrievalStore:
        """Save a retrieval store."""

    @abstractmethod
    async def find_by_id(self, tenant_id: str, store_id: str) -> RetrievalStore | None:
        """Find a non-deleted store by id scoped to tenant."""

    async def find_by_ids(self, tenant_id: str, store_ids: list[str]) -> dict[str, RetrievalStore]:
        """Find multiple non-deleted stores by id, keyed by store id.

        The default implementation issues one query per id; backends should
        override it with a single IN query to avoid N+1 reads.
        """
        stores: dict[str, RetrievalStore] = {}
        for store_id in dict.fromkeys(store_ids):
            store = await self.find_by_id(tenant_id, store_id)
            if store is not None:
                stores[store_id] = store
        return stores

    @abstractmethod
    async def find_by_name(self, tenant_id: str, name: str) -> RetrievalStore | None:
        """Find a non-deleted store by tenant + name."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[RetrievalStore]:
        """List non-deleted stores for a tenant."""

    @abstractmethod
    async def count_projects_bound(self, store_id: str) -> int:
        """Count projects bound to this retrieval store."""

    @abstractmethod
    async def soft_delete(self, tenant_id: str, store_id: str) -> bool:
        """Soft-delete a store."""
