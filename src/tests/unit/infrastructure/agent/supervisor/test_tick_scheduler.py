"""Unit tests for the supervisor tick scheduler (Track B P2-3 phase-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from src.infrastructure.agent.supervisor.tick_scheduler import (
    SupervisorTickState,
    TickTrigger,
    decide,
    should_breakloop,
    should_budget_risk,
    should_stale,
    should_tick,
)

NOW = datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC)


class TestShouldTick:
    def test_first_tick_fires_when_no_prior(self) -> None:
        assert should_tick(None, tick_seconds=120, now=NOW) is True

    def test_does_not_fire_before_interval(self) -> None:
        last = NOW - timedelta(seconds=60)
        assert should_tick(last, tick_seconds=120, now=NOW) is False

    def test_fires_at_interval(self) -> None:
        last = NOW - timedelta(seconds=120)
        assert should_tick(last, tick_seconds=120, now=NOW) is True

    def test_zero_interval_disabled(self) -> None:
        assert should_tick(None, tick_seconds=0, now=NOW) is False


class TestShouldStale:
    def test_never_stale_without_baseline(self) -> None:
        assert should_stale(None, stale_threshold_seconds=300, now=NOW) is False

    def test_under_threshold(self) -> None:
        progress = NOW - timedelta(seconds=100)
        assert should_stale(progress, stale_threshold_seconds=300, now=NOW) is False

    def test_at_threshold(self) -> None:
        progress = NOW - timedelta(seconds=300)
        assert should_stale(progress, stale_threshold_seconds=300, now=NOW) is True

    def test_zero_threshold_disabled(self) -> None:
        progress = NOW - timedelta(seconds=999)
        assert should_stale(progress, stale_threshold_seconds=0, now=NOW) is False


class TestShouldBreakloop:
    def test_under_threshold(self) -> None:
        assert should_breakloop(doom_loop_counter=2, max_loops=3) is False

    def test_at_threshold(self) -> None:
        assert should_breakloop(doom_loop_counter=3, max_loops=3) is True

    def test_over_threshold(self) -> None:
        assert should_breakloop(doom_loop_counter=10, max_loops=3) is True

    def test_zero_threshold_disabled(self) -> None:
        assert should_breakloop(doom_loop_counter=5, max_loops=0) is False


class TestShouldBudgetRisk:
    def test_under_warn_ratio(self) -> None:
        assert should_budget_risk(projected_spend=0.8, budget_cap=1.0, warn_ratio=0.9) is False

    def test_at_warn_ratio(self) -> None:
        assert should_budget_risk(projected_spend=0.9, budget_cap=1.0, warn_ratio=0.9) is True

    def test_over_cap(self) -> None:
        assert should_budget_risk(projected_spend=1.5, budget_cap=1.0, warn_ratio=0.9) is True

    def test_zero_cap_disabled(self) -> None:
        assert should_budget_risk(projected_spend=100.0, budget_cap=0.0) is False


class TestDecidePriority:
    @pytest.fixture
    def state(self) -> SupervisorTickState:
        return SupervisorTickState(
            conversation_id="conv-1", last_tick_at=NOW - timedelta(seconds=200)
        )

    def test_doom_loop_beats_everything(self, state: SupervisorTickState) -> None:
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=5,
            max_loops=3,
            projected_spend=10.0,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=9999),
            now=NOW,
        )
        assert decision.should_fire is True
        assert decision.trigger == TickTrigger.DOOM_LOOP
        assert decision.signals["doom_loop_counter"] == "5"

    def test_stale_beats_budget_and_tick(self, state: SupervisorTickState) -> None:
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=0,
            max_loops=3,
            projected_spend=10.0,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=1000),
            now=NOW,
        )
        assert decision.trigger == TickTrigger.STALE

    def test_budget_beats_tick(self, state: SupervisorTickState) -> None:
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=0,
            max_loops=3,
            projected_spend=10.0,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=10),
            now=NOW,
        )
        assert decision.trigger == TickTrigger.BUDGET

    def test_tick_fires_when_others_quiet(self, state: SupervisorTickState) -> None:
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=0,
            max_loops=3,
            projected_spend=0.1,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=10),
            now=NOW,
        )
        assert decision.trigger == TickTrigger.TICK

    def test_nothing_fires_in_quiet_steady_state(self) -> None:
        state = SupervisorTickState(
            conversation_id="conv-1",
            last_tick_at=NOW - timedelta(seconds=10),
        )
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=0,
            max_loops=3,
            projected_spend=0.1,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=10),
            now=NOW,
        )
        assert decision.should_fire is False
        assert decision.trigger == TickTrigger.NONE

    def test_signals_carry_structural_numbers_only(self, state: SupervisorTickState) -> None:
        decision = decide(
            state,
            tick_seconds=120,
            stale_threshold_seconds=300,
            doom_loop_counter=2,
            max_loops=3,
            projected_spend=0.5,
            budget_cap=1.0,
            last_progress_at=NOW - timedelta(seconds=50),
            now=NOW,
        )
        for value in decision.signals.values():
            assert isinstance(value, str)
        assert decision.signals["doom_loop_counter"] == "2"
        assert decision.signals["projected_spend"] == "0.5000"
        assert "last_progress_at" in decision.signals
