from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .enums import EffectMetricType, EvolutionEventType, InstanceGeneStatus


@dataclass(kw_only=True)
class InstanceGene(Entity):
    instance_id: str
    gene_id: str
    genome_id: str | None = None
    status: InstanceGeneStatus = InstanceGeneStatus.installing
    installed_version: str | None = None
    learning_output: str | None = None
    config_snapshot: dict[str, Any] = field(default_factory=dict)
    agent_self_eval: str | None = None
    usage_count: int = 0
    variant_published: bool = False
    installed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    def __post_init__(self) -> None:
        if not self.instance_id:
            raise ValueError("instance_id cannot be empty")
        if not self.gene_id:
            raise ValueError("gene_id cannot be empty")

    def is_active(self) -> bool:
        return self.status == InstanceGeneStatus.installed

    def soft_delete(self) -> None:
        self.deleted_at = datetime.now(UTC)


@dataclass(kw_only=True)
class GeneEffectLog(Entity):
    instance_id: str
    gene_id: str
    metric_type: EffectMetricType = EffectMetricType.custom
    value: float = 0.0
    context: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class GeneRating(Entity):
    gene_id: str
    user_id: str
    rating: int = 0
    comment: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class GenomeRating(Entity):
    genome_id: str
    user_id: str
    rating: int = 0
    comment: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(kw_only=True)
class GeneReview(Entity):
    """A user review for a gene (text content + rating)."""

    gene_id: str
    user_id: str
    rating: int = 0
    content: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None

    def soft_delete(self) -> None:
        """Soft-delete this review."""
        self.deleted_at = datetime.now(UTC)


@dataclass(kw_only=True)
class EvolutionEvent(Entity):
    instance_id: str
    gene_id: str | None = None
    genome_id: str | None = None
    event_type: EvolutionEventType = EvolutionEventType.learned
    gene_name: str = ""
    gene_slug: str | None = None
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
