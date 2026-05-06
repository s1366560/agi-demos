"""Pure recovery verdict logic — no agent tool-call needed.

The verdict is structural: given a lease, a heartbeat, and current task fields,
decide whether the task should be left alone, marked timed out, or marked as
transitioned (because terminal artifacts already exist).

This is one of the Agent-First exemptions: "timers and tick triggers (the tick
is objective; the verdict it triggers must be agent-judged)" — but here the
verdict itself is also objective because we're only choosing between
record-keeping outcomes, not making any quality judgment.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum

from src.domain.model.recovery.lease import ExecutionLease, LeaseStatus
from src.domain.shared_kernel import ValueObject


class RecoveryAction(str, Enum):
    """What to do with a task that *claims* to be running."""

    KEEP = "keep"  # lease still valid, executor still present
    MARK_TIMED_OUT = "mark_timed_out"  # no executor, no terminal artifact
    MARK_TRANSITIONED = "mark_transitioned"  # already has terminal artifact (verification/completion)
    RELEASE_LEASE = "release_lease"  # owned by a dead instance, free it but keep status


@dataclass(frozen=True, kw_only=True)
class StaleTaskInput(ValueObject):
    """Snapshot of a possibly-stale task as seen by the recovery scanner."""

    task_id: str
    project_id: str
    lease: ExecutionLease | None
    has_verification_report: bool = False
    has_completion_summary: bool = False
    last_stream_activity_at: datetime | None = None
    """Latest entry on ``agent:events:{conversation_id}`` Redis stream, if known."""


@dataclass(frozen=True, kw_only=True)
class RecoveryVerdict(ValueObject):
    """Final action + a human-readable reason, used by audit log."""

    task_id: str
    action: RecoveryAction
    reason: str


# Heartbeat freshness window: if no Redis stream activity for this long AND
# the lease has expired, the task is dead. 10 minutes is the routa default.
DEFAULT_HEARTBEAT_STALE_AFTER = timedelta(minutes=10)


def decide_recovery_action(  # noqa: PLR0911 — decision tree with 7 distinct outcomes by design
    snapshot: StaleTaskInput,
    *,
    now: datetime,
    current_instance_id: str,
    heartbeat_stale_after: timedelta = DEFAULT_HEARTBEAT_STALE_AFTER,
) -> RecoveryVerdict:
    """Pure function — produce the recovery verdict for one stale task.

    Decision tree:

    1. No lease at all → ``MARK_TIMED_OUT`` (we have nothing to keep)
    2. Lease owned by a different instance:
       - lease still active → ``KEEP``
       - lease expired      → ``RELEASE_LEASE``
    3. Lease owned by current instance:
       - lease active and heartbeat fresh → ``KEEP``
       - terminal artifact present        → ``MARK_TRANSITIONED``
       - otherwise                         → ``MARK_TIMED_OUT``
    """
    # 1. No lease.
    if snapshot.lease is None:
        if snapshot.has_verification_report or snapshot.has_completion_summary:
            return RecoveryVerdict(
                task_id=snapshot.task_id,
                action=RecoveryAction.MARK_TRANSITIONED,
                reason="No active lease but terminal artifact present.",
            )
        return RecoveryVerdict(
            task_id=snapshot.task_id,
            action=RecoveryAction.MARK_TIMED_OUT,
            reason="No active lease and no terminal artifact.",
        )

    lease_status = snapshot.lease.status(now=now, current_instance_id=current_instance_id)
    is_owned_locally = snapshot.lease.instance_id == current_instance_id

    # 2. Lease owned by a different instance.
    if not is_owned_locally:
        if lease_status is LeaseStatus.ACTIVE:
            return RecoveryVerdict(
                task_id=snapshot.task_id,
                action=RecoveryAction.KEEP,
                reason=f"Active lease owned by instance {snapshot.lease.instance_id}.",
            )
        # Foreign instance, expired lease — free it.
        return RecoveryVerdict(
            task_id=snapshot.task_id,
            action=RecoveryAction.RELEASE_LEASE,
            reason=f"Expired lease from foreign instance {snapshot.lease.instance_id}.",
        )

    # 3. Lease owned locally.
    if lease_status is LeaseStatus.ACTIVE and _heartbeat_is_fresh(
        snapshot.last_stream_activity_at, now=now, stale_after=heartbeat_stale_after
    ):
        return RecoveryVerdict(
            task_id=snapshot.task_id,
            action=RecoveryAction.KEEP,
            reason="Active local lease and recent stream activity.",
        )

    if snapshot.has_verification_report or snapshot.has_completion_summary:
        return RecoveryVerdict(
            task_id=snapshot.task_id,
            action=RecoveryAction.MARK_TRANSITIONED,
            reason="Local lease stale; terminal artifact already recorded.",
        )

    return RecoveryVerdict(
        task_id=snapshot.task_id,
        action=RecoveryAction.MARK_TIMED_OUT,
        reason="Local lease stale and no terminal artifact.",
    )


def _heartbeat_is_fresh(
    last_activity_at: datetime | None,
    *,
    now: datetime,
    stale_after: timedelta,
) -> bool:
    """A missing heartbeat is considered stale (we never saw it alive)."""
    if last_activity_at is None:
        return False
    if last_activity_at.tzinfo is None:
        # Coerce naive timestamps into UTC to avoid mixed-aware comparisons.
        last_activity_at = last_activity_at.replace(tzinfo=UTC)
    return (now - last_activity_at) < stale_after
