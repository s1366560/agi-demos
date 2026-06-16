"""Repository interface for InstanceTemplate and TemplateItem entities."""

from abc import ABC, abstractmethod

from src.domain.model.instance_template.instance_template import (
    InstanceTemplate,
    TemplateItem,
)


class InstanceTemplateRepository(ABC):
    """Repository interface for InstanceTemplate entity."""

    @abstractmethod
    async def save(self, domain_entity: InstanceTemplate) -> InstanceTemplate:
        """Save a template (create or update). Returns the saved template."""

    @abstractmethod
    async def find_by_id(self, entity_id: str) -> InstanceTemplate | None:
        """Find a template by ID."""

    @abstractmethod
    async def find_by_slug(self, slug: str) -> InstanceTemplate | None:
        """Find a template by slug."""

    @abstractmethod
    async def find_by_tenant(
        self, tenant_id: str, limit: int = 50, offset: int = 0
    ) -> list[InstanceTemplate]:
        """List all templates in a tenant."""

    async def find_by_filters(
        self,
        *,
        tenant_id: str,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InstanceTemplate]:
        """List templates with filters applied before pagination."""
        raise NotImplementedError

    async def count_by_filters(
        self,
        *,
        tenant_id: str,
        is_published: bool | None = None,
    ) -> int:
        """Count templates matching the same filters used for listing."""
        raise NotImplementedError

    @abstractmethod
    async def find_featured(self, limit: int = 20) -> list[InstanceTemplate]:
        """List featured templates."""

    @abstractmethod
    async def delete(self, entity_id: str) -> bool:
        """Delete a template. Returns True if deleted, False if not found."""

    @abstractmethod
    async def save_item(self, item: TemplateItem) -> TemplateItem:
        """Save a template item (create or update). Returns the saved item."""

    @abstractmethod
    async def find_items_by_template(self, template_id: str) -> list[TemplateItem]:
        """List all items in a template."""

    @abstractmethod
    async def delete_item(self, item_id: str) -> bool:
        """Delete a template item. Returns True if deleted, False if not found."""
