"""Mutation transaction metadata model for self-modifying operations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class MutationTransactionStatus(str, Enum):
    """Lifecycle status for one mutation transaction."""

    PLAN = "plan"
    DRY_RUN = "dry_run"
    APPLIED = "applied"
    VERIFIED = "verified"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass(kw_only=True)
class MutationTransaction:
    """Mutable transaction record with ordered lifecycle timeline."""

    source: str
    action: str
    trace_id: str
    tenant_id: str | None = None
    project_id: str | None = None
    plugin_name: str | None = None
    requirement: str | None = None
    transaction_id: str = field(default_factory=lambda: f"mutation:{uuid4().hex}")
    status: MutationTransactionStatus = MutationTransactionStatus.PLAN
    timeline: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.add_phase(self.status, details={})

    def add_phase(
        self,
        status: MutationTransactionStatus,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append one lifecycle phase and update current status."""
        self.status = status
        self.timeline.append(
            {
                "phase": status.value,
                "timestamp": datetime.now(UTC).isoformat(),
                "details": details or {},
            }
        )

    def to_dict(self) -> dict[str, Any]:
        """Serialize transaction for metadata/event payloads."""
        return {
            "transaction_id": self.transaction_id,
            "source": self.source,
            "action": self.action,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "project_id": self.project_id,
            "plugin_name": self.plugin_name,
            "requirement": self.requirement,
            "status": self.status.value,
            "timeline": list(self.timeline),
        }
