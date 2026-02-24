from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class APIKey(Entity):
    """API Key domain entity for authentication"""

    user_id: str
    key_hash: str
    name: str
    is_active: bool = True
    permissions: list[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
