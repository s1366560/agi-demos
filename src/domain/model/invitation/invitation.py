from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class Invitation(Entity):
    """A tenant-scoped invitation for a user to join via email."""

    tenant_id: str
    email: str
    role: str = "member"
    token: str = ""
    status: str = "pending"
    invited_by: str = ""
    accepted_by: str | None = None
    expires_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
