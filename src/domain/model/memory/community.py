from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Community(Entity):
    name: str
    summary: str
    member_count: int = 0
    tenant_id: Optional[str] = None
    project_id: Optional[str] = None
    formed_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
