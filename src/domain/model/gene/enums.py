"""Gene bounded context enums."""

from enum import Enum


class ContentVisibility(str, Enum):
    """Visibility level for genes and genomes in the marketplace."""

    public = "public"
    org_private = "org_private"


class GeneSource(str, Enum):
    """Origin of a gene."""

    official = "official"
    community = "community"
    self_created = "self_created"
    forked = "forked"
    emerged = "emerged"


class GeneReviewStatus(str, Enum):
    """Review status for marketplace publication."""

    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    auto_approved = "auto_approved"


class InstanceGeneStatus(str, Enum):
    """Lifecycle status of a gene installed on an instance."""

    installing = "installing"
    installed = "installed"
    learning = "learning"
    failed = "failed"
    learn_failed = "learn_failed"
    uninstalling = "uninstalling"
    simplified = "simplified"
    forgetting = "forgetting"
    forget_failed = "forget_failed"


class EvolutionEventType(str, Enum):
    """Type of evolution event on an instance."""

    learned = "learned"
    forgot = "forgot"
    upgraded = "upgraded"
    created_variant = "created_variant"
    installed_genome = "installed_genome"
    uninstalled_genome = "uninstalled_genome"
    simplified = "simplified"


class EffectMetricType(str, Enum):
    """Metric type for measuring gene effectiveness."""

    response_quality = "response_quality"
    task_completion = "task_completion"
    user_satisfaction = "user_satisfaction"
    custom = "custom"
