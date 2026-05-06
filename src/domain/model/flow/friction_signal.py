"""Friction signal — a single bounce/retry/abort/timeout event observed in
agent task execution.

Distilled from routa's `flow-ledger.ts`: every time a task moves backwards,
times out, or is aborted, we emit a structured friction signal so downstream
analytics + reflection can learn from it.

This is a **value object**: signals are append-only and never mutated.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

from src.domain.shared_kernel import ValueObject


class FrictionKind(str, Enum):
    """Why this friction was recorded.

    - `bounce`:   task moved back to an earlier lane (e.g. dev → todo)
    - `retry`:    task re-executed after a failed attempt
    - `abort`:    task cancelled by user or supervisor
    - `timeout`:  task exceeded its wall-clock budget
    - `gate_block`: lane contract evidence missing (e.g. no test_results)
    """

    BOUNCE = "bounce"
    RETRY = "retry"
    ABORT = "abort"
    TIMEOUT = "timeout"
    GATE_BLOCK = "gate_block"


@dataclass(frozen=True)
class FrictionSignal(ValueObject):
    """Append-only signal recording a single friction event."""

    project_id: str
    task_id: str
    kind: FrictionKind
    source_lane: str | None = None
    target_lane: str | None = None
    """Optional free-form metadata (tool name, error class, retry count, ...)."""
    metadata: dict[str, object] = field(default_factory=dict)
    """When the friction was observed. Immutable, defaults to now."""
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
