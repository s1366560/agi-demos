from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class User(Entity):
    """User domain entity representing a system user"""

    email: str
    name: str
    password_hash: str
    is_active: bool = True
    profile: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
