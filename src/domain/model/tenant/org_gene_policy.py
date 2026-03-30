"""Domain model for Organization Gene Policy."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class OrgGenePolicy(Entity):
    """Organization-level gene policy controlling gene marketplace behavior."""

    tenant_id: str
    policy_key: str
    policy_value: dict[str, object] = field(default_factory=dict)
    description: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
