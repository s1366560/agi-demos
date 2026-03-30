from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Webhook(Entity):
    tenant_id: str
    name: str
    url: str
    secret: str | None = None
    events: list[str] = field(default_factory=list)
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None

    def update(
        self, name: str, url: str, secret: str | None, events: list[str], is_active: bool
    ) -> None:
        self.name = name
        self.url = url
        self.secret = secret
        self.events = events
        self.is_active = is_active
        self.updated_at = datetime.now(UTC)

    def delete(self) -> None:
        self.deleted_at = datetime.now(UTC)
