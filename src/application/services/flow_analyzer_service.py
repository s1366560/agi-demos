"""Flow Ledger analyzer (deterministic aggregation half).

Consumes a sequence of column-transition events and produces deterministic
metrics + bounce/hotspot/friction patterns. Authoring of ``FlowGuidanceItem``
narratives is delegated to an agent tool-call (see Agent First rule), so this
module returns a ``FlowLedgerSnapshot`` with ``guidance=()`` and a separate
``preflight_signals()`` helper that surfaces the deterministic triggers the
agent should rationalize.
"""

from __future__ import annotations

import statistics
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from src.domain.model.flow import (
    BouncePattern,
    FailureHotspot,
    FlowLedgerSnapshot,
    HandoffFriction,
    LaneMetrics,
    RecoveryReason,
)


@dataclass(frozen=True, kw_only=True)
class TransitionEvent:
    """One observed column-to-column transition for a task."""

    workspace_id: str
    task_id: str
    from_column_id: str | None
    to_column_id: str
    column_name: str | None = None
    duration_ms: int = 0
    outcome: str = "completed"  # completed | failed | timeout | recovered
    response_time_ms: int = 0
    blocked: bool = False
    failed: bool = False
    recovery_reason: str | None = None
    occurred_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, kw_only=True)
class PreflightSignal:
    """Deterministic trigger handed to the diagnosis agent."""

    kind: str
    severity: str  # info | warning | critical
    affected_columns: tuple[str, ...]
    metric: dict[str, float | int | str]


def _safe_div(num: float, den: float) -> float:
    return num / den if den else 0.0


def aggregate_lane_metrics(events: Iterable[TransitionEvent]) -> tuple[LaneMetrics, ...]:
    by_col: dict[str, list[TransitionEvent]] = defaultdict(list)
    names: dict[str, str | None] = {}
    for ev in events:
        by_col[ev.to_column_id].append(ev)
        if ev.column_name and ev.to_column_id not in names:
            names[ev.to_column_id] = ev.column_name

    metrics: list[LaneMetrics] = []
    for col_id, items in by_col.items():
        total = len(items)
        completed = sum(1 for e in items if e.outcome == "completed")
        failed = sum(1 for e in items if e.outcome in ("failed", "timeout"))
        recovered = sum(1 for e in items if e.outcome == "recovered")
        durations = [e.duration_ms for e in items if e.outcome == "completed" and e.duration_ms]
        metrics.append(
            LaneMetrics(
                column_id=col_id,
                column_name=names.get(col_id),
                total_sessions=total,
                completed_sessions=completed,
                failed_sessions=failed,
                recovered_sessions=recovered,
                avg_duration_ms=float(sum(durations) / len(durations)) if durations else 0.0,
                median_duration_ms=float(statistics.median(durations)) if durations else 0.0,
                failure_rate=_safe_div(failed, total),
                recovery_rate=_safe_div(recovered, total),
            )
        )
    return tuple(sorted(metrics, key=lambda m: m.column_id))


def detect_bounce_patterns(
    events: Iterable[TransitionEvent], min_occurrences: int = 2
) -> tuple[BouncePattern, ...]:
    by_pair: dict[tuple[str, str], list[str]] = defaultdict(list)
    for ev in events:
        if ev.from_column_id is None:
            continue
        # Bounce = backward transition (heuristic: marked outcome=recovered or
        # any explicit "back to <col>"). We treat any non-forward transition
        # as a bounce candidate when from < to lexically differs.
        if ev.from_column_id == ev.to_column_id:
            continue
        by_pair[(ev.from_column_id, ev.to_column_id)].append(ev.task_id)

    patterns: list[BouncePattern] = []
    for (frm, to), task_ids in by_pair.items():
        # Bounce iff reverse pair also exists for the same task.
        reverse = by_pair.get((to, frm), [])
        common = sorted(set(task_ids) & set(reverse))
        if len(common) >= min_occurrences:
            patterns.append(
                BouncePattern(
                    from_column_id=frm,
                    to_column_id=to,
                    occurrences=len(common),
                    task_ids=tuple(common),
                    avg_bounce_count=_safe_div(len(task_ids) + len(reverse), len(common) or 1),
                )
            )
    return tuple(patterns)


def detect_failure_hotspots(
    events: Iterable[TransitionEvent], min_failures: int = 3
) -> tuple[FailureHotspot, ...]:
    by_col: dict[str, list[TransitionEvent]] = defaultdict(list)
    names: dict[str, str | None] = {}
    for ev in events:
        if ev.outcome in ("failed", "timeout"):
            by_col[ev.to_column_id].append(ev)
            if ev.column_name:
                names.setdefault(ev.to_column_id, ev.column_name)

    spots: list[FailureHotspot] = []
    for col_id, items in by_col.items():
        if len(items) < min_failures:
            continue
        timeout_count = sum(1 for e in items if e.outcome == "timeout")
        reasons: dict[str, int] = defaultdict(int)
        for e in items:
            if e.recovery_reason:
                reasons[e.recovery_reason] += 1
        top = tuple(
            RecoveryReason(reason=r, count=c)
            for r, c in sorted(reasons.items(), key=lambda p: -p[1])[:3]
        )
        spots.append(
            FailureHotspot(
                column_id=col_id,
                column_name=names.get(col_id),
                failure_count=len(items),
                timeout_count=timeout_count,
                top_recovery_reasons=top,
            )
        )
    return tuple(spots)


def detect_handoff_friction(events: Iterable[TransitionEvent]) -> tuple[HandoffFriction, ...]:
    by_pair: dict[tuple[str, str], list[TransitionEvent]] = defaultdict(list)
    for ev in events:
        if ev.from_column_id is None:
            continue
        by_pair[(ev.from_column_id, ev.to_column_id)].append(ev)

    out: list[HandoffFriction] = []
    for (frm, to), items in by_pair.items():
        total = len(items)
        blocked = sum(1 for e in items if e.blocked)
        failed = sum(1 for e in items if e.failed)
        rt = [e.response_time_ms for e in items if e.response_time_ms]
        out.append(
            HandoffFriction(
                from_column_id=frm,
                to_column_id=to,
                total_handoffs=total,
                blocked_handoffs=blocked,
                failed_handoffs=failed,
                avg_response_time_ms=float(sum(rt) / len(rt)) if rt else 0.0,
                friction_rate=_safe_div(blocked + failed, total),
            )
        )
    return tuple(out)


def build_snapshot(workspace_id: str, events: list[TransitionEvent]) -> FlowLedgerSnapshot:
    """Produce a deterministic snapshot. Guidance items are populated separately
    by the agent diagnosis tool-call."""
    return FlowLedgerSnapshot(
        workspace_id=workspace_id,
        lane_metrics=aggregate_lane_metrics(events),
        bounce_patterns=detect_bounce_patterns(events),
        failure_hotspots=detect_failure_hotspots(events),
        handoff_friction=detect_handoff_friction(events),
        guidance=(),
    )


def preflight_signals(snapshot: FlowLedgerSnapshot) -> tuple[PreflightSignal, ...]:
    """Convert the deterministic snapshot into trigger signals for an agent.

    The agent's job is to decide *what to recommend* given these signals — the
    severity bucketing here is only a circuit-breaker, not a verdict.
    """
    signals: list[PreflightSignal] = []
    for m in snapshot.lane_metrics:
        if m.failure_rate >= 0.5 and m.total_sessions >= 4:
            signals.append(
                PreflightSignal(
                    kind="lane_high_failure",
                    severity="critical",
                    affected_columns=(m.column_id,),
                    metric={"failure_rate": m.failure_rate, "total": m.total_sessions},
                )
            )
        elif m.failure_rate >= 0.25 and m.total_sessions >= 4:
            signals.append(
                PreflightSignal(
                    kind="lane_elevated_failure",
                    severity="warning",
                    affected_columns=(m.column_id,),
                    metric={"failure_rate": m.failure_rate, "total": m.total_sessions},
                )
            )
    for b in snapshot.bounce_patterns:
        signals.append(
            PreflightSignal(
                kind="bounce_pattern",
                severity="warning" if b.occurrences < 5 else "critical",
                affected_columns=(b.from_column_id, b.to_column_id),
                metric={"occurrences": b.occurrences, "avg_count": b.avg_bounce_count},
            )
        )
    for f in snapshot.handoff_friction:
        if f.friction_rate >= 0.4 and f.total_handoffs >= 5:
            signals.append(
                PreflightSignal(
                    kind="handoff_friction",
                    severity="warning",
                    affected_columns=(f.from_column_id, f.to_column_id),
                    metric={"friction_rate": f.friction_rate, "total": f.total_handoffs},
                )
            )
    return tuple(signals)


__all__ = [
    "PreflightSignal",
    "TransitionEvent",
    "aggregate_lane_metrics",
    "build_snapshot",
    "detect_bounce_patterns",
    "detect_failure_hotspots",
    "detect_handoff_friction",
    "preflight_signals",
]
