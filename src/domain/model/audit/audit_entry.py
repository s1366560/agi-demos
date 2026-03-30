from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class AuditEntry(Entity):
    """A single audit log record for tracking sensitive operations."""

    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    actor: str | None = None
    action: str = ""
    resource_type: str = ""
    resource_id: str | None = None
    tenant_id: str | None = None
    details: dict[str, object] = field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
