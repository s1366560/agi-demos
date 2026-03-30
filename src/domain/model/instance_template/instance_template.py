"""InstanceTemplate and TemplateItem domain entities."""

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import TemplateItemType


@dataclass(kw_only=True)
class InstanceTemplate(Entity):
    """Template defining a reusable instance configuration."""

    name: str
    slug: str
    tenant_id: str | None = None
    description: str | None = None
    icon: str | None = None
    image_version: str | None = None
    default_config: dict[str, Any] = field(default_factory=dict)
    is_published: bool = False
    is_featured: bool = False
    install_count: int = 0
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("name cannot be empty")
        if not self.slug:
            raise ValueError("slug cannot be empty")

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)


@dataclass(kw_only=True)
class TemplateItem(Entity):
    """An item (gene or genome) included in an instance template."""

    template_id: str
    item_type: TemplateItemType = TemplateItemType.gene
    item_slug: str
    display_order: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.template_id:
            raise ValueError("template_id cannot be empty")
        if not self.item_slug:
            raise ValueError("item_slug cannot be empty")
