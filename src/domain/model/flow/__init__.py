"""Flow Ledger domain types.

Distilled from routa's `src/core/kanban/flow-ledger-types.ts`. Provides a
structured aggregation of cross-task/cross-board flow patterns that:

- ``BouncePattern`` — tasks repeatedly moving between two columns
- ``LaneMetrics`` — per-column throughput / failure / recovery
- ``FailureHotspot`` — disproportionately failing lanes
- ``HandoffFriction`` — friction between adjacent lanes
- ``FlowGuidanceItem`` — actionable recommendation derived from the above

These dataclasses are pure value objects: no I/O, no ORM. The supervising
``FlowAnalyzerService`` (see ``application/services``) is expected to consume
raw transition events from a repository and produce a ``FlowLedgerSnapshot``.

Per the project rule **Agent First**, the *trigger* (e.g. "bounce_count > 3")
is computed deterministically here, but the *verdict* and *recommendation*
must be authored by an agent tool-call when populating ``FlowGuidanceItem``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum


class FlowGuidanceSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class FlowGuidanceCategory(str, Enum):
    BOUNCE_PATTERN = "bounce_pattern"
    FAILURE_HOTSPOT = "failure_hotspot"
    HANDOFF_FRICTION = "handoff_friction"
    LANE_BOTTLENECK = "lane_bottleneck"


@dataclass(frozen=True, kw_only=True)
class BouncePattern:
    """Tasks repeatedly moving between two columns."""

    from_column_id: str
    to_column_id: str
    occurrences: int
    task_ids: tuple[str, ...] = field(default_factory=tuple)
    avg_bounce_count: float


@dataclass(frozen=True, kw_only=True)
class LaneMetrics:
    """Aggregated metrics for a single lane/column."""

    column_id: str
    column_name: str | None
    total_sessions: int
    completed_sessions: int
    failed_sessions: int
    recovered_sessions: int
    avg_duration_ms: float
    median_duration_ms: float
    failure_rate: float
    recovery_rate: float


@dataclass(frozen=True, kw_only=True)
class RecoveryReason:
    reason: str
    count: int


@dataclass(frozen=True, kw_only=True)
class FailureHotspot:
    """A lane with a disproportionate share of failures."""

    column_id: str
    column_name: str | None
    failure_count: int
    timeout_count: int
    top_recovery_reasons: tuple[RecoveryReason, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class HandoffFriction:
    """Friction report between two adjacent lanes."""

    from_column_id: str
    to_column_id: str
    total_handoffs: int
    blocked_handoffs: int
    failed_handoffs: int
    avg_response_time_ms: float
    friction_rate: float  # 0.0 – 1.0


@dataclass(frozen=True, kw_only=True)
class FlowGuidanceItem:
    """A single actionable guidance item.

    Populated by the agent tool-call layer. Determinism here applies to fields
    that come from arithmetic counters (``severity`` enum value); the natural
    language ``summary`` and ``recommendation`` MUST be authored by an agent.
    """

    category: FlowGuidanceCategory
    severity: FlowGuidanceSeverity
    summary: str
    recommendation: str
    affected_columns: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, kw_only=True)
class FlowLedgerSnapshot:
    """Complete read-model snapshot for one workspace at one moment."""

    workspace_id: str
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    lane_metrics: tuple[LaneMetrics, ...] = field(default_factory=tuple)
    bounce_patterns: tuple[BouncePattern, ...] = field(default_factory=tuple)
    failure_hotspots: tuple[FailureHotspot, ...] = field(default_factory=tuple)
    handoff_friction: tuple[HandoffFriction, ...] = field(default_factory=tuple)
    guidance: tuple[FlowGuidanceItem, ...] = field(default_factory=tuple)


__all__ = [
    "BouncePattern",
    "FailureHotspot",
    "FlowGuidanceCategory",
    "FlowGuidanceItem",
    "FlowGuidanceSeverity",
    "FlowLedgerSnapshot",
    "HandoffFriction",
    "LaneMetrics",
    "RecoveryReason",
]
