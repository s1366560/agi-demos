"""
InstanceTemplateService: Business logic for instance template management.

This service handles template CRUD operations and template item management,
following the hexagonal architecture pattern.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from src.domain.model.instance_template.enums import TemplateItemType
from src.domain.model.instance_template.instance_template import (
    InstanceTemplate,
    TemplateItem,
)
from src.domain.ports.repositories.instance_template_repository import (
    InstanceTemplateRepository,
)

logger = logging.getLogger(__name__)


class InstanceTemplateService:
    """Service for managing instance templates and their items."""

    def __init__(
        self,
        template_repo: InstanceTemplateRepository,
    ) -> None:
        self._template_repo = template_repo

    # ------------------------------------------------------------------
    # Template CRUD
    # ------------------------------------------------------------------

    async def create_template(
        self,
        name: str,
        slug: str,
        created_by: str,
        tenant_id: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        image_version: str | None = None,
        default_config: dict[str, Any] | None = None,
    ) -> InstanceTemplate:
        """
        Create a new instance template.

        Args:
            name: Template name.
            slug: URL-friendly identifier.
            created_by: User ID of the creator.
            tenant_id: Optional tenant scope.
            description: Optional template description.
            icon: Optional icon identifier.
            image_version: Optional Docker image version.
            default_config: Optional default configuration dict.

        Returns:
            Created template.
        """
        template = InstanceTemplate(
            name=name,
            slug=slug,
            created_by=created_by,
            tenant_id=tenant_id,
            description=description,
            icon=icon,
            image_version=image_version,
            default_config=default_config or {},
        )

        saved = await self._template_repo.save(template)
        logger.info(
            "Created template %s (slug=%s) for tenant %s",
            saved.id,
            slug,
            tenant_id,
        )
        return saved

    async def get_template(
        self,
        template_id: str,
    ) -> InstanceTemplate | None:
        """
        Retrieve a template by ID.

        Args:
            template_id: Template ID.

        Returns:
            Template if found, None otherwise.
        """
        return await self._template_repo.find_by_id(template_id)

    async def list_templates(
        self,
        tenant_id: str | None = None,
        is_published: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[InstanceTemplate]:
        """
        List templates with optional filtering.

        Args:
            tenant_id: Optional tenant ID to scope results.
            is_published: Optional filter on published status.
            limit: Maximum number of results.
            offset: Number of results to skip.

        Returns:
            List of templates matching the criteria.
        """
        if tenant_id is not None:
            templates = await self._template_repo.find_by_tenant(
                tenant_id,
                limit=limit,
                offset=offset,
            )
        else:
            # No tenant scope — fetch global templates via tenant repo
            # with empty string to represent "no tenant".
            templates = await self._template_repo.find_by_tenant(
                "",
                limit=limit,
                offset=offset,
            )

        if is_published is not None:
            templates = [t for t in templates if t.is_published == is_published]

        return templates

    async def update_template(
        self,
        template_id: str,
        name: str | None = None,
        description: str | None = None,
        icon: str | None = None,
        image_version: str | None = None,
        default_config: dict[str, Any] | None = None,
        is_published: bool | None = None,
    ) -> InstanceTemplate:
        """
        Update template properties.

        Args:
            template_id: Template ID.
            name: New name (optional).
            description: New description (optional).
            icon: New icon (optional).
            image_version: New image version (optional).
            default_config: New default config (optional).
            is_published: New published status (optional).

        Returns:
            Updated template.

        Raises:
            ValueError: If template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        if name is not None:
            template.name = name
        if description is not None:
            template.description = description
        if icon is not None:
            template.icon = icon
        if image_version is not None:
            template.image_version = image_version
        if default_config is not None:
            template.default_config = default_config
        if is_published is not None:
            template.is_published = is_published

        template.updated_at = datetime.now(UTC)

        saved = await self._template_repo.save(template)
        logger.info("Updated template %s", template_id)
        return saved

    async def delete_template(self, template_id: str) -> None:
        """
        Soft-delete a template.

        Args:
            template_id: Template ID.

        Raises:
            ValueError: If template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        template.soft_delete()
        _ = await self._template_repo.save(template)
        logger.info("Soft-deleted template %s", template_id)

    async def publish_template(
        self,
        template_id: str,
    ) -> InstanceTemplate:
        """
        Publish a template (set is_published=True).

        Args:
            template_id: Template ID.

        Returns:
            Updated template.

        Raises:
            ValueError: If template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        template.is_published = True
        template.updated_at = datetime.now(UTC)

        saved = await self._template_repo.save(template)
        logger.info("Published template %s", template_id)
        return saved

    async def unpublish_template(
        self,
        template_id: str,
    ) -> InstanceTemplate:
        """
        Unpublish a template (set is_published=False).

        Args:
            template_id: Template ID.

        Returns:
            Updated template.

        Raises:
            ValueError: If template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        template.is_published = False
        template.updated_at = datetime.now(UTC)

        saved = await self._template_repo.save(template)
        logger.info("Unpublished template %s", template_id)
        return saved

    # ------------------------------------------------------------------
    # Template Items
    # ------------------------------------------------------------------

    async def add_template_item(
        self,
        template_id: str,
        item_type: TemplateItemType,
        item_slug: str,
        display_order: int = 0,
    ) -> TemplateItem:
        """
        Add an item to a template.

        Args:
            template_id: Template to add the item to.
            item_type: Type of the item (gene or genome).
            item_slug: Slug identifying the item.
            display_order: Ordering position within the template.

        Returns:
            Created template item.

        Raises:
            ValueError: If template does not exist.
        """
        template = await self._template_repo.find_by_id(template_id)
        if not template:
            raise ValueError(f"Template {template_id} not found")

        item = TemplateItem(
            template_id=template_id,
            item_type=item_type,
            item_slug=item_slug,
            display_order=display_order,
        )

        saved = await self._template_repo.save_item(item)
        logger.info(
            "Added item %s (type=%s, slug=%s) to template %s",
            saved.id,
            item_type.value,
            item_slug,
            template_id,
        )
        return saved

    async def remove_template_item(self, item_id: str) -> None:
        """
        Soft-delete a template item.

        Args:
            item_id: Template item ID.

        Raises:
            ValueError: If template item does not exist.
        """
        deleted = await self._template_repo.delete_item(item_id)
        if not deleted:
            raise ValueError(f"Template item {item_id} not found")
        logger.info("Removed template item %s", item_id)

    async def list_template_items(
        self,
        template_id: str,
    ) -> list[TemplateItem]:
        """
        List all items belonging to a template.

        Args:
            template_id: Template ID.

        Returns:
            List of template items.
        """
        return await self._template_repo.find_items_by_template(
            template_id,
        )
