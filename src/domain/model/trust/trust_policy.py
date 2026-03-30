from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class TrustPolicy(Entity):
    """Graduated autonomy policy granting an agent permission for specific actions."""

    tenant_id: str
    workspace_id: str
    agent_instance_id: str
    action_type: str
    granted_by: str
    grant_type: str  # "once" | "always"
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
