"""Recovery domain — lease-based ghost-task reconciliation.

Distilled from routa's `restart-recovery.ts`. When a worker process restarts
or a Ray actor crashes, tasks marked ``running`` may have no live executor.
This module models lease ownership and the deterministic verdict for what
should happen to each stale running task.

The verdict logic is purely structural (lease expiry, instance ownership,
heartbeat freshness) — no agent tool-call needed. See AGENTS.md → Agent-First
exemptions ("set-membership / arithmetic / protocol facts").
"""

from src.domain.model.recovery.lease import ExecutionLease, LeaseStatus
from src.domain.model.recovery.verdict import (
    RecoveryAction,
    RecoveryVerdict,
    StaleTaskInput,
)

__all__ = [
    "ExecutionLease",
    "LeaseStatus",
    "RecoveryAction",
    "RecoveryVerdict",
    "StaleTaskInput",
]
