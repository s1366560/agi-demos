from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity


@dataclass(kw_only=True)
class DecisionRecord(Entity):
    """Records a decision request and its resolution outcome."""

    tenant_id: str
    workspace_id: str
    agent_instance_id: str
    decision_type: str
    context_summary: str | None = None
    proposal: dict[str, Any] = field(default_factory=dict)
    outcome: str = "pending"  # "pending" | "success" | "rejected"
    reviewer_id: str | None = None
    review_type: str | None = None  # "human" | "auto"
    review_comment: str | None = None
    resolved_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None
    deleted_at: datetime | None = None
