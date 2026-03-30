"""Domain model for Registry Configuration."""

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class RegistryConfig(Entity):
    """Container registry configuration for a tenant."""

    tenant_id: str
    name: str
    registry_type: str
    url: str
    username: str | None = None
    password_encrypted: str | None = None
    is_default: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
