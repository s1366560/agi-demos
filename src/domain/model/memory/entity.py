from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from src.domain.shared_kernel import Entity as BaseEntity


@dataclass(kw_only=True)
class Entity(BaseEntity):
    name: str
    entity_type: str
    summary: str = ""
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    properties: Dict[str, Any] = field(default_factory=dict)

    def update_summary(self, new_summary: str) -> None:
        self.summary = new_summary
