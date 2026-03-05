"""CronJobRun domain entity.

Records the outcome of a single cron-job execution.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from src.domain.shared_kernel import Entity

from .value_objects import CronRunStatus, TriggerType


@dataclass(kw_only=True)
class CronJobRun(Entity):
    """Immutable log entry for one execution of a CronJob."""

    job_id: str
    project_id: str
    status: CronRunStatus
    trigger_type: TriggerType = TriggerType.SCHEDULED
    started_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    duration_ms: int | None = None
    error_message: str | None = None
    result_summary: dict[str, Any] = field(default_factory=dict)
    conversation_id: str | None = None

    def mark_finished(
        self,
        status: CronRunStatus,
        error_message: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> None:
        now = datetime.now(UTC)
        self.status = status
        self.finished_at = now
        if self.started_at:
            delta = now - self.started_at
            self.duration_ms = int(delta.total_seconds() * 1000)
        if error_message is not None:
            self.error_message = error_message
        if result_summary is not None:
            self.result_summary = result_summary
