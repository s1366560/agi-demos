"""
SubAgentTemplateRepository port for template marketplace persistence.

Repository interface for persisting and retrieving SubAgent templates.
"""

from abc import ABC, abstractmethod


class SubAgentTemplateRepositoryPort(ABC):
    """Repository port for SubAgent template persistence."""

    @abstractmethod
    async def create(self, template: dict) -> dict:
        """Create a new template. Returns the created template as dict."""

    @abstractmethod
    async def get_by_id(self, template_id: str) -> dict | None:
        """Get a template by ID."""

    @abstractmethod
    async def get_by_name(
        self, tenant_id: str, name: str, version: str | None = None
    ) -> dict | None:
        """Get a template by name within a tenant, optionally by version."""

    @abstractmethod
    async def update(self, template_id: str, data: dict) -> dict | None:
        """Update a template. Returns updated template or None."""

    @abstractmethod
    async def delete(self, template_id: str) -> bool:
        """Delete a template. Returns True if deleted."""

    @abstractmethod
    async def list_templates(
        self,
        tenant_id: str,
        category: str | None = None,
        tags: list[str] | None = None,
        query: str | None = None,
        published_only: bool = True,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        """List templates with filtering."""

    @abstractmethod
    async def count_templates(
        self,
        tenant_id: str,
        category: str | None = None,
        published_only: bool = True,
    ) -> int:
        """Count templates matching filters."""

    @abstractmethod
    async def list_categories(self, tenant_id: str) -> list[str]:
        """List distinct categories for a tenant."""

    @abstractmethod
    async def increment_install_count(self, template_id: str) -> None:
        """Increment the install count for a template."""
