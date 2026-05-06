"""Tests for FlowAnalyzerService deterministic aggregation."""

from datetime import UTC, datetime, timedelta

import pytest

from src.application.services.flow_analyzer_service import (
    TransitionEvent,
    aggregate_lane_metrics,
    build_snapshot,
    detect_bounce_patterns,
    detect_failure_hotspots,
    detect_handoff_friction,
    preflight_signals,
)


def _ev(**overrides) -> TransitionEvent:
    base: dict = {
        "workspace_id": "ws-1",
        "task_id": "t-1",
        "from_column_id": "todo",
        "to_column_id": "dev",
        "column_name": "Dev",
        "duration_ms": 1000,
        "outcome": "completed",
        "response_time_ms": 50,
        "blocked": False,
        "failed": False,
        "recovery_reason": None,
        "occurred_at": datetime.now(UTC),
    }
    base.update(overrides)
    return TransitionEvent(**base)


@pytest.mark.unit
class TestLaneMetrics:
    def test_empty_input_returns_empty_tuple(self):
        assert aggregate_lane_metrics([]) == ()

    def test_failure_and_recovery_rates(self):
        events = [
            _ev(outcome="completed", duration_ms=1000),
            _ev(outcome="failed"),
            _ev(outcome="recovered"),
            _ev(outcome="completed", duration_ms=2000),
        ]
        metrics = aggregate_lane_metrics(events)
        assert len(metrics) == 1
        m = metrics[0]
        assert m.total_sessions == 4
        assert m.completed_sessions == 2
        assert m.failed_sessions == 1
        assert m.recovered_sessions == 1
        assert m.failure_rate == 0.25
        assert m.recovery_rate == 0.25
        assert m.avg_duration_ms == 1500.0
        assert m.median_duration_ms == 1500.0


@pytest.mark.unit
class TestBouncePatterns:
    def test_no_bounce_when_unidirectional(self):
        events = [_ev(task_id="t1", from_column_id="todo", to_column_id="dev")]
        assert detect_bounce_patterns(events) == ()

    def test_detects_bidirectional_bounce(self):
        events = [
            _ev(task_id="t1", from_column_id="dev", to_column_id="review"),
            _ev(task_id="t1", from_column_id="review", to_column_id="dev"),
            _ev(task_id="t2", from_column_id="dev", to_column_id="review"),
            _ev(task_id="t2", from_column_id="review", to_column_id="dev"),
        ]
        patterns = detect_bounce_patterns(events, min_occurrences=2)
        assert len(patterns) >= 1
        pair = {(p.from_column_id, p.to_column_id) for p in patterns}
        assert ("dev", "review") in pair or ("review", "dev") in pair


@pytest.mark.unit
class TestFailureHotspots:
    def test_below_threshold_ignored(self):
        events = [_ev(outcome="failed"), _ev(outcome="failed")]
        assert detect_failure_hotspots(events, min_failures=3) == ()

    def test_at_threshold_reported(self):
        events = [
            _ev(outcome="failed"),
            _ev(outcome="failed"),
            _ev(outcome="timeout"),
            _ev(outcome="failed", recovery_reason="retry_exhausted"),
        ]
        spots = detect_failure_hotspots(events, min_failures=3)
        assert len(spots) == 1
        spot = spots[0]
        assert spot.failure_count == 4
        assert spot.timeout_count == 1
        assert spot.top_recovery_reasons[0].reason == "retry_exhausted"


@pytest.mark.unit
class TestHandoffFriction:
    def test_friction_rate_calculation(self):
        events = [
            _ev(blocked=True),
            _ev(failed=True),
            _ev(),
            _ev(),
        ]
        friction = detect_handoff_friction(events)
        assert len(friction) == 1
        assert friction[0].friction_rate == 0.5


@pytest.mark.unit
class TestPreflightSignals:
    def test_critical_failure_lane_signal(self):
        events = [_ev(outcome="failed") for _ in range(3)] + [_ev(outcome="completed")]
        snap = build_snapshot("ws-1", events)
        signals = preflight_signals(snap)
        kinds = {s.kind for s in signals}
        assert "lane_high_failure" in kinds

    def test_no_signals_on_healthy_flow(self):
        events = [_ev(outcome="completed") for _ in range(10)]
        snap = build_snapshot("ws-1", events)
        signals = preflight_signals(snap)
        assert not any(s.severity in ("warning", "critical") for s in signals)


@pytest.mark.unit
def test_build_snapshot_leaves_guidance_empty():
    """Determinism boundary: deterministic build never authors guidance."""
    snap = build_snapshot("ws-1", [_ev()])
    assert snap.guidance == ()
    assert snap.workspace_id == "ws-1"
    assert isinstance(snap.generated_at, datetime)
    assert snap.generated_at <= datetime.now(UTC) + timedelta(seconds=1)
