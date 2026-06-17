"""Repository interface for Gene entity."""

from abc import ABC, abstractmethod

from src.domain.model.gene.gene import Gene


class GeneRepository(ABC):
    """Repository interface for Gene entity."""

    @abstractmethod
    async def save(self, domain_entity: Gene) -> Gene:
        """Save a gene (create or update). Returns the saved gene."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> Gene | None:
        """Find a gene by ID."""

    @abstractmethod
    async def find_by_slug(self, slug: str) -> Gene | None:
        """Find a gene by slug."""

    @abstractmethod
    async def find_by_tenant(self, tenant_id: str, limit: int = 50, offset: int = 0) -> list[Gene]:
        """List all genes in a tenant."""

    async def find_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
        exclude_installed_instance_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        """List genes with filters applied before pagination."""
        raise NotImplementedError

    async def count_by_filters(
        self,
        *,
        tenant_id: str | None = None,
        category: str | None = None,
        search: str | None = None,
        visibility: str | None = None,
        is_published: bool | None = None,
        exclude_installed_instance_id: str | None = None,
    ) -> int:
        """Count genes matching the same filters used for listing."""
        raise NotImplementedError

    @abstractmethod
    async def search(
        self,
        query: str,
        category: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Gene]:
        """Search genes by query string and optional category."""

    @abstractmethod
    async def find_featured(self, limit: int = 20) -> list[Gene]:
        """List featured genes."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a gene. Returns True if deleted, False if not found."""
