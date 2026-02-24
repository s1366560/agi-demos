from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity as BaseEntity


@dataclass(kw_only=True)
class Entity(BaseEntity):
    name: str
    entity_type: str
    summary: str = ""
    tenant_id: str | None = None
    project_id: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    properties: dict[str, Any] = field(default_factory=dict)

    def update_summary(self, new_summary: str) -> None:
        self.summary = new_summary
