from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import ContentVisibility, GeneReviewStatus, GeneSource


@dataclass(kw_only=True)
class Gene(Entity):
    name: str
    slug: str
    tenant_id: str | None = None
    description: str | None = None
    short_description: str | None = None
    category: str | None = None
    tags: list[str] = field(default_factory=list)
    source: GeneSource = GeneSource.official
    source_ref: str | None = None
    icon: str | None = None
    version: str = "1.0.0"
    manifest: dict[str, Any] = field(default_factory=dict)
    dependencies: list[str] = field(default_factory=list)
    synergies: list[str] = field(default_factory=list)
    parent_gene_id: str | None = None
    created_by_instance_id: str | None = None
    install_count: int = 0
    avg_rating: float = 0.0
    effectiveness_score: float = 0.0
    is_featured: bool = False
    review_status: GeneReviewStatus = GeneReviewStatus.pending
    is_published: bool = False
    visibility: ContentVisibility = ContentVisibility.public
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("Gene name cannot be empty")
        if not self.slug:
            raise ValueError("Gene slug cannot be empty")


@dataclass(kw_only=True)
class Genome(Entity):
    name: str
    slug: str
    tenant_id: str | None = None
    description: str | None = None
    short_description: str | None = None
    icon: str | None = None
    gene_slugs: list[str] = field(default_factory=list)
    config_override: dict[str, Any] = field(default_factory=dict)
    install_count: int = 0
    avg_rating: float = 0.0
    is_featured: bool = False
    is_published: bool = False
    visibility: ContentVisibility = ContentVisibility.public
    created_by: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
