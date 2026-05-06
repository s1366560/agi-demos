"""Unit tests for the recovery domain + service.

Covers:
- Lease status classification (active / expired / unowned / foreign)
- Recovery verdict decision matrix (8 cases)
- TaskRecoveryService end-to-end with in-memory adapters
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import override

import pytest

from src.application.services.task_recovery_service import (
    RecoveryReport,
    StaleTaskScanner,
    TaskRecoveryService,
    TaskStatusMutator,
)
from src.domain.model.recovery.lease import ExecutionLease, LeaseStatus
from src.domain.model.recovery.verdict import (
    RecoveryAction,
    StaleTaskInput,
    decide_recovery_action,
)
from src.infrastructure.adapters.secondary.in_memory.execution_lease_repository import (
    InMemoryExecutionLeaseRepository,
)


@pytest.mark.unit
class TestExecutionLease:
    def test_active_when_expires_in_future_and_owned_locally(self) -> None:
        now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-A",
            expires_at=now + timedelta(minutes=5),
        )
        assert lease.status(now=now, current_instance_id="inst-A") is LeaseStatus.ACTIVE

    def test_expired_when_past_deadline(self) -> None:
        now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-A",
            expires_at=now - timedelta(seconds=1),
        )
        assert lease.status(now=now, current_instance_id="inst-A") is LeaseStatus.EXPIRED

    def test_foreign_active_lease_is_active(self) -> None:
        now = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-B",
            expires_at=now + timedelta(minutes=5),
        )
        assert lease.status(now=now, current_instance_id="inst-A") is LeaseStatus.ACTIVE


@pytest.mark.unit
class TestRecoveryVerdict:
    NOW = datetime(2026, 5, 6, 10, 0, tzinfo=UTC)

    def _decide(self, snap: StaleTaskInput, *, instance: str = "inst-A"):
        return decide_recovery_action(snap, now=self.NOW, current_instance_id=instance)

    def test_no_lease_no_artifact_marks_timed_out(self) -> None:
        snap = StaleTaskInput(task_id="t1", project_id="p1", lease=None)
        verdict = self._decide(snap)
        assert verdict.action is RecoveryAction.MARK_TIMED_OUT

    def test_no_lease_with_completion_summary_marks_transitioned(self) -> None:
        snap = StaleTaskInput(
            task_id="t1",
            project_id="p1",
            lease=None,
            has_completion_summary=True,
        )
        assert self._decide(snap).action is RecoveryAction.MARK_TRANSITIONED

    def test_no_lease_with_verification_report_marks_transitioned(self) -> None:
        snap = StaleTaskInput(
            task_id="t1",
            project_id="p1",
            lease=None,
            has_verification_report=True,
        )
        assert self._decide(snap).action is RecoveryAction.MARK_TRANSITIONED

    def test_foreign_active_lease_keeps(self) -> None:
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-B",
            expires_at=self.NOW + timedelta(minutes=5),
        )
        snap = StaleTaskInput(task_id="t1", project_id="p1", lease=lease)
        verdict = self._decide(snap)
        assert verdict.action is RecoveryAction.KEEP

    def test_foreign_expired_lease_releases(self) -> None:
        lease = ExecutionLease.expired_at("t1", "inst-B")
        snap = StaleTaskInput(task_id="t1", project_id="p1", lease=lease)
        assert self._decide(snap).action is RecoveryAction.RELEASE_LEASE

    def test_local_active_lease_with_fresh_heartbeat_keeps(self) -> None:
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-A",
            expires_at=self.NOW + timedelta(minutes=5),
        )
        snap = StaleTaskInput(
            task_id="t1",
            project_id="p1",
            lease=lease,
            last_stream_activity_at=self.NOW - timedelta(seconds=30),
        )
        assert self._decide(snap).action is RecoveryAction.KEEP

    def test_local_active_lease_with_stale_heartbeat_marks_timed_out(self) -> None:
        lease = ExecutionLease(
            task_id="t1",
            instance_id="inst-A",
            expires_at=self.NOW + timedelta(minutes=5),
        )
        snap = StaleTaskInput(
            task_id="t1",
            project_id="p1",
            lease=lease,
            last_stream_activity_at=self.NOW - timedelta(hours=1),
        )
        assert self._decide(snap).action is RecoveryAction.MARK_TIMED_OUT

    def test_local_expired_lease_with_terminal_artifact_marks_transitioned(self) -> None:
        lease = ExecutionLease.expired_at("t1", "inst-A")
        snap = StaleTaskInput(
            task_id="t1",
            project_id="p1",
            lease=lease,
            has_completion_summary=True,
        )
        assert self._decide(snap).action is RecoveryAction.MARK_TRANSITIONED


# ---------------------------------------------------------------------------
# Service-level test fixtures
# ---------------------------------------------------------------------------


@dataclass
class _FixedClock:
    now_value: datetime

    def now(self) -> datetime:
        return self.now_value


@dataclass
class _FakeScanner(StaleTaskScanner):
    snapshots: list[StaleTaskInput] = field(default_factory=list)

    async def scan(self, project_id: str) -> list[StaleTaskInput]:  # type: ignore[override]
        return [s for s in self.snapshots if s.project_id == project_id]


@dataclass
class _FakeMutator(TaskStatusMutator):
    timed_out: list[tuple[str, str]] = field(default_factory=list)
    transitioned: list[tuple[str, str]] = field(default_factory=list)

    @override
    async def mark_timed_out(self, *, project_id: str, task_id: str, reason: str) -> None:
        self.timed_out.append((project_id, task_id))

    @override
    async def mark_transitioned(self, *, project_id: str, task_id: str, reason: str) -> None:
        self.transitioned.append((project_id, task_id))


@pytest.mark.unit
class TestTaskRecoveryService:
    @pytest.fixture
    def now(self) -> datetime:
        return datetime(2026, 5, 6, 10, 0, tzinfo=UTC)

    async def test_reconcile_dispatches_each_action(self, now: datetime) -> None:
        scanner = _FakeScanner(
            snapshots=[
                # 1. dead local task → mark_timed_out
                StaleTaskInput(
                    task_id="t-dead",
                    project_id="p1",
                    lease=ExecutionLease.expired_at("t-dead", "inst-A"),
                ),
                # 2. dead local task with terminal artifact → mark_transitioned
                StaleTaskInput(
                    task_id="t-done",
                    project_id="p1",
                    lease=ExecutionLease.expired_at("t-done", "inst-A"),
                    has_completion_summary=True,
                ),
                # 3. live local task → keep
                StaleTaskInput(
                    task_id="t-alive",
                    project_id="p1",
                    lease=ExecutionLease(
                        task_id="t-alive",
                        instance_id="inst-A",
                        expires_at=now + timedelta(minutes=5),
                    ),
                    last_stream_activity_at=now - timedelta(seconds=10),
                ),
                # 4. foreign expired lease → release_lease only
                StaleTaskInput(
                    task_id="t-foreign",
                    project_id="p1",
                    lease=ExecutionLease.expired_at("t-foreign", "inst-B"),
                ),
            ]
        )
        mutator = _FakeMutator()
        leases = InMemoryExecutionLeaseRepository()
        # Seed leases so we can assert release behavior.
        for snap in scanner.snapshots:
            if snap.lease is not None:
                await leases.upsert(project_id="p1", lease=snap.lease)

        service = TaskRecoveryService(
            scanner=scanner,
            mutator=mutator,
            lease_repo=leases,
            current_instance_id="inst-A",
            clock=_FixedClock(now),
        )

        report = await service.reconcile_project("p1")

        assert isinstance(report, RecoveryReport)
        assert mutator.timed_out == [("p1", "t-dead")]
        assert mutator.transitioned == [("p1", "t-done")]
        # Both stale tasks + the foreign one had their leases released.
        assert await leases.get(project_id="p1", task_id="t-dead") is None
        assert await leases.get(project_id="p1", task_id="t-done") is None
        assert await leases.get(project_id="p1", task_id="t-foreign") is None
        # The live one is untouched.
        assert (
            await leases.get(project_id="p1", task_id="t-alive")
        ) is not None
        assert report.total_changed == 3
        assert len(report.by_action(RecoveryAction.KEEP)) == 1

    async def test_reconcile_with_no_running_tasks_is_a_noop(self, now: datetime) -> None:
        service = TaskRecoveryService(
            scanner=_FakeScanner(),
            mutator=_FakeMutator(),
            lease_repo=InMemoryExecutionLeaseRepository(),
            current_instance_id="inst-A",
            clock=_FixedClock(now),
        )
        report = await service.reconcile_project("p1")
        assert report.verdicts == ()
        assert report.total_changed == 0

    def test_rejects_empty_instance_id(self) -> None:
        with pytest.raises(ValueError):
            TaskRecoveryService(
                scanner=_FakeScanner(),
                mutator=_FakeMutator(),
                lease_repo=InMemoryExecutionLeaseRepository(),
                current_instance_id="",
            )
