"""Recovery service — scans stale tasks and applies the deterministic verdict.

Wiring:
- Called from the FastAPI ``lifespan`` startup hook (one-shot per project)
- Also exposed as an admin endpoint for ad-hoc reconciliation
- Does NOT make agent tool-calls; verdict is purely structural

The service does not own task storage. It depends on three thin protocols:
- ``StaleTaskScanner`` — produces ``StaleTaskInput`` snapshots for tasks
  currently marked ``running`` in the project
- ``TaskStatusMutator`` — applies verdicts (mark_timed_out / mark_transitioned)
- ``ExecutionLeaseRepository`` — releases stale foreign leases

This indirection keeps the service free of ORM/DB imports and lets us reuse
the same logic for SQL-backed and in-memory stores in tests.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable

from src.domain.model.recovery.verdict import (
    DEFAULT_HEARTBEAT_STALE_AFTER,
    RecoveryAction,
    RecoveryVerdict,
    StaleTaskInput,
    decide_recovery_action,
)
from src.domain.ports.repositories.execution_lease_repository import (
    ExecutionLeaseRepository,
)


@runtime_checkable
class StaleTaskScanner(Protocol):
    """Adapter that knows how to project DB tasks into ``StaleTaskInput``s."""

    async def scan(self, project_id: str) -> list[StaleTaskInput]:  # pragma: no cover - protocol
        ...


@runtime_checkable
class TaskStatusMutator(Protocol):
    """Adapter that applies a verdict to the underlying task store."""

    async def mark_timed_out(self, *, project_id: str, task_id: str, reason: str) -> None: ...

    async def mark_transitioned(self, *, project_id: str, task_id: str, reason: str) -> None: ...


@dataclass(frozen=True)
class RecoveryReport:
    project_id: str
    started_at: datetime
    finished_at: datetime
    verdicts: tuple[RecoveryVerdict, ...] = field(default_factory=tuple)

    def by_action(self, action: RecoveryAction) -> tuple[RecoveryVerdict, ...]:
        return tuple(v for v in self.verdicts if v.action is action)

    @property
    def total_changed(self) -> int:
        return sum(1 for v in self.verdicts if v.action is not RecoveryAction.KEEP)


class TaskRecoveryService:
    """Reconciles stale ``running`` tasks against current lease + heartbeat truth."""

    def __init__(
        self,
        *,
        scanner: StaleTaskScanner,
        mutator: TaskStatusMutator,
        lease_repo: ExecutionLeaseRepository,
        current_instance_id: str,
        heartbeat_stale_after: timedelta = DEFAULT_HEARTBEAT_STALE_AFTER,
        clock: object | None = None,
    ) -> None:
        if not current_instance_id:
            raise ValueError("current_instance_id must be a non-empty string")
        self._scanner = scanner
        self._mutator = mutator
        self._lease_repo = lease_repo
        self._instance_id = current_instance_id
        self._stale_after = heartbeat_stale_after
        # Optional clock for tests; default = real wall clock.
        self._clock = clock

    def _now(self) -> datetime:
        if self._clock is not None and hasattr(self._clock, "now"):
            return self._clock.now()  # type: ignore[no-any-return]
        return datetime.now(UTC)

    async def reconcile_project(self, project_id: str) -> RecoveryReport:
        """Scan + apply verdicts for one project. Idempotent."""
        started = self._now()
        snapshots = await self._scanner.scan(project_id)
        verdicts: list[RecoveryVerdict] = []
        for snap in snapshots:
            verdict = decide_recovery_action(
                snap,
                now=self._now(),
                current_instance_id=self._instance_id,
                heartbeat_stale_after=self._stale_after,
            )
            verdicts.append(verdict)
            await self._apply(project_id, verdict)

        return RecoveryReport(
            project_id=project_id,
            started_at=started,
            finished_at=self._now(),
            verdicts=tuple(verdicts),
        )

    async def _apply(self, project_id: str, verdict: RecoveryVerdict) -> None:
        if verdict.action is RecoveryAction.KEEP:
            return
        if verdict.action is RecoveryAction.MARK_TIMED_OUT:
            await self._mutator.mark_timed_out(
                project_id=project_id,
                task_id=verdict.task_id,
                reason=verdict.reason,
            )
            await self._lease_repo.release(project_id=project_id, task_id=verdict.task_id)
            return
        if verdict.action is RecoveryAction.MARK_TRANSITIONED:
            await self._mutator.mark_transitioned(
                project_id=project_id,
                task_id=verdict.task_id,
                reason=verdict.reason,
            )
            await self._lease_repo.release(project_id=project_id, task_id=verdict.task_id)
            return
        if verdict.action is RecoveryAction.RELEASE_LEASE:
            await self._lease_repo.release(project_id=project_id, task_id=verdict.task_id)
            return
