from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Community(Entity):
    name: str
    summary: str
    member_count: int = 0
    tenant_id: str | None = None
    project_id: str | None = None
    formed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
