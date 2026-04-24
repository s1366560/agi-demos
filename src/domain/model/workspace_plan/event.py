"""Durable event records for workspace plan execution."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class WorkspacePlanEvent(Entity):
    """Append-only audit/event entry for a workspace plan."""

    plan_id: str
    workspace_id: str
    event_type: str
    node_id: str | None = None
    attempt_id: str | None = None
    actor_id: str | None = None
    source: str = "system"
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not self.plan_id:
            raise ValueError("WorkspacePlanEvent.plan_id cannot be empty")
        if not self.workspace_id:
            raise ValueError("WorkspacePlanEvent.workspace_id cannot be empty")
        if not self.event_type:
            raise ValueError("WorkspacePlanEvent.event_type cannot be empty")


__all__ = ["WorkspacePlanEvent"]
