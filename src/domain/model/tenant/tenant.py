from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Tenant(Entity):
    """Tenant domain entity for multi-tenancy support"""

    name: str
    owner_id: str
    description: Optional[str] = None
    plan: str = "free"
    max_projects: int = 3
    max_users: int = 10
    max_storage: int = 1073741824  # 1GB in bytes
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: Optional[datetime] = None
