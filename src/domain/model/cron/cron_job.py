"""CronJob domain entity.

Represents a scheduled task scoped to a project. Follows the same
``@dataclass(kw_only=True)`` + ``Entity`` pattern as other MemStack domain models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .value_objects import (
    ConversationMode,
    CronDelivery,
    CronPayload,
    CronSchedule,
    DeliveryType,
)

# Default backoff schedule (milliseconds) — ported from OpenClaw
DEFAULT_BACKOFF_SCHEDULE_MS: list[int] = [
    30_000,  # 30 s
    60_000,  # 1 min
    300_000,  # 5 min
    900_000,  # 15 min
    3_600_000,  # 60 min
]


@dataclass(kw_only=True)
class CronJob(Entity):
    """A scheduled task belonging to a project.

    Attributes:
        project_id: Owning project (multi-tenant scope).
        tenant_id: Owning tenant.
        name: Human-readable job name.
        description: Optional longer description.
        enabled: Whether the scheduler should fire this job.
        delete_after_run: If True the job is deleted after its first successful run.
        schedule: When the job fires (at | every | cron).
        payload: What the job does (system_event | agent_turn).
        delivery: How the result is delivered (none | announce | webhook).
        conversation_mode: Reuse existing conversation or create a fresh one.
        conversation_id: Conversation to reuse (when mode == reuse).
        timezone: IANA timezone for schedule evaluation (default UTC).
        stagger_seconds: Deterministic per-job offset for load spreading.
        timeout_seconds: Max execution time per run.
        max_retries: Max consecutive failures before disabling.
        state: Mutable runtime state (next_run, last_run, errors, backoff).
        created_by: User who created the job.
        created_at / updated_at: Audit timestamps.
    """

    # -- Identity & scope ---------------------------------------------------
    project_id: str
    tenant_id: str

    # -- Configuration ------------------------------------------------------
    name: str
    description: str | None = None
    enabled: bool = True
    delete_after_run: bool = False

    # -- Schedule / payload / delivery (value objects) ----------------------
    schedule: CronSchedule = field(default_factory=lambda: CronSchedule.cron(expr="0 * * * *"))
    payload: CronPayload = field(default_factory=lambda: CronPayload.agent_turn(message=""))
    delivery: CronDelivery = field(default_factory=CronDelivery.none)

    # -- Conversation strategy ----------------------------------------------
    conversation_mode: ConversationMode = ConversationMode.REUSE
    conversation_id: str | None = None

    # -- Execution params ---------------------------------------------------
    timezone: str = "UTC"
    stagger_seconds: int = 0
    timeout_seconds: int = 300
    max_retries: int = 3

    # -- Runtime state (persisted as JSON) ----------------------------------
    state: dict[str, Any] = field(default_factory=dict)

    # -- Audit --------------------------------------------------------------
    created_by: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime | None = None

    # -- Domain behaviour ---------------------------------------------------

    def disable(self) -> None:
        """Disable the job (e.g. after max retries exceeded)."""
        self.enabled = False
        self.updated_at = datetime.now(UTC)

    def enable(self) -> None:
        """Re-enable a disabled job, resetting error counters."""
        self.enabled = True
        self.state["consecutive_errors"] = 0
        self.state.pop("backoff_until", None)
        self.updated_at = datetime.now(UTC)

    def record_success(self, now: datetime | None = None) -> None:
        """Update state after a successful run."""
        now = now or datetime.now(UTC)
        self.state["last_run_at"] = now.isoformat()
        self.state["last_run_status"] = "success"
        self.state["consecutive_errors"] = 0
        self.state.pop("backoff_until", None)
        self.updated_at = now

    def record_failure(
        self,
        error: str,
        now: datetime | None = None,
        backoff_schedule: list[int] | None = None,
    ) -> None:
        """Update state after a failed run; apply exponential backoff."""
        now = now or datetime.now(UTC)
        schedule = backoff_schedule or DEFAULT_BACKOFF_SCHEDULE_MS

        consecutive = int(self.state.get("consecutive_errors", 0)) + 1
        self.state["last_run_at"] = now.isoformat()
        self.state["last_run_status"] = "failed"
        self.state["last_error"] = error
        self.state["consecutive_errors"] = consecutive

        # Backoff: pick delay from schedule, capped at last entry
        idx = min(consecutive - 1, len(schedule) - 1)
        backoff_ms = schedule[idx]
        from datetime import timedelta

        backoff_until = now + timedelta(milliseconds=backoff_ms)
        self.state["backoff_until"] = backoff_until.isoformat()

        self.updated_at = now

        # Auto-disable after max retries
        if consecutive >= self.max_retries:
            self.disable()

    def is_one_shot(self) -> bool:
        """Return True if this is a one-shot (``at``) schedule."""
        from .value_objects import ScheduleType

        return self.schedule.kind == ScheduleType.AT

    def should_delete_after_run(self) -> bool:
        """Return True if the job should be removed after a successful run."""
        return self.delete_after_run or self.is_one_shot()

    def is_delivery_none(self) -> bool:
        return self.delivery.kind == DeliveryType.NONE

    def touch(self) -> None:
        """Bump ``updated_at``."""
        self.updated_at = datetime.now(UTC)
