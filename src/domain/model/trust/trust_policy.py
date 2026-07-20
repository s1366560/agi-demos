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
    scope: str = "agent"
    canonical_tool_name: str | None = None
    source_hitl_request_id: str | None = None
    revision: int = 0
    revoked_by: str | None = None
    revoked_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    deleted_at: datetime | None = None
