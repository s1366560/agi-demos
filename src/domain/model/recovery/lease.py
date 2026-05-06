"""Execution lease — proof that a specific instance owns a task right now."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import ValueObject


class LeaseStatus(str, Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    UNOWNED = "unowned"


@dataclass(frozen=True, kw_only=True)
class ExecutionLease(ValueObject):
    """A claim that ``instance_id`` is executing ``task_id`` until ``expires_at``.

    Pure value object. Multi-tenant scoping (``project_id``) is enforced at the
    repository layer, not here.
    """

    task_id: str
    instance_id: str
    expires_at: datetime
    last_heartbeat_at: datetime | None = None

    def status(self, *, now: datetime, current_instance_id: str) -> LeaseStatus:
        """Classify the lease relative to a given clock + current instance.

        Pure function — no I/O, no clock dependency. Caller injects ``now``.
        """
        if not self.instance_id:
            return LeaseStatus.UNOWNED
        if self.expires_at <= now:
            return LeaseStatus.EXPIRED
        if self.instance_id != current_instance_id:
            # Some other instance still holds an active lease — leave it alone.
            return LeaseStatus.ACTIVE
        return LeaseStatus.ACTIVE

    @classmethod
    def expired_at(
        cls, task_id: str, instance_id: str, when: datetime | None = None
    ) -> ExecutionLease:
        """Convenience constructor for tests: a lease that already expired."""
        return cls(
            task_id=task_id,
            instance_id=instance_id,
            expires_at=when or datetime(1970, 1, 1, tzinfo=UTC),
        )
