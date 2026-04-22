"""Unit tests for TerminationReason / BudgetCounters / gate evaluators."""

from __future__ import annotations

import pytest

from src.domain.model.agent.conversation.termination import (
    BudgetCounters,
    TerminationDecision,
    TerminationReason,
    evaluate_budget,
    evaluate_safety,
)
from src.domain.model.agent.conversation.verdict_status import VerdictStatus


class TestTerminationReason:
    def test_gate_mapping(self) -> None:
        assert TerminationReason.GOAL_COMPLETED.gate == "goal"
        assert TerminationReason.BUDGET_TURNS.gate == "budget"
        assert TerminationReason.BUDGET_USD.gate == "budget"
        assert TerminationReason.BUDGET_WALL_SECONDS.gate == "budget"
        assert TerminationReason.SAFETY_LOOPING.gate == "safety"
        assert TerminationReason.SAFETY_DOOM_LOOP.gate == "safety"
        assert TerminationReason.USER_CANCEL.gate == "user"


class TestBudgetCounters:
    def test_defaults_zero(self) -> None:
        c = BudgetCounters()
        assert c.turns == 0 and c.usd == 0.0 and c.wall_seconds == 0

    def test_negative_rejected(self) -> None:
        with pytest.raises(ValueError):
            BudgetCounters(turns=-1)
        with pytest.raises(ValueError):
            BudgetCounters(usd=-0.01)
        with pytest.raises(ValueError):
            BudgetCounters(wall_seconds=-1)


class TestEvaluateBudget:
    def test_unbounded_caps_dont_fire(self) -> None:
        assert (
            evaluate_budget(
                max_turns=None,
                max_usd=None,
                max_wall_seconds=None,
                counters=BudgetCounters(turns=9999, usd=9999.0),
            )
            is None
        )

    def test_turns_gate_fires_at_cap(self) -> None:
        d = evaluate_budget(
            max_turns=10,
            max_usd=None,
            max_wall_seconds=None,
            counters=BudgetCounters(turns=10),
        )
        assert d is not None
        assert d.reason is TerminationReason.BUDGET_TURNS
        assert "turns=10" in d.rationale

    def test_usd_gate_fires(self) -> None:
        d = evaluate_budget(
            max_turns=None,
            max_usd=1.0,
            max_wall_seconds=None,
            counters=BudgetCounters(usd=1.0),
        )
        assert d is not None
        assert d.reason is TerminationReason.BUDGET_USD

    def test_wall_seconds_gate_fires(self) -> None:
        d = evaluate_budget(
            max_turns=None,
            max_usd=None,
            max_wall_seconds=60,
            counters=BudgetCounters(wall_seconds=60),
        )
        assert d is not None
        assert d.reason is TerminationReason.BUDGET_WALL_SECONDS

    def test_turns_wins_over_usd_in_fixed_order(self) -> None:
        d = evaluate_budget(
            max_turns=5,
            max_usd=1.0,
            max_wall_seconds=None,
            counters=BudgetCounters(turns=5, usd=2.0),
        )
        assert d is not None
        assert d.reason is TerminationReason.BUDGET_TURNS


class TestEvaluateSafety:
    def test_returns_none_without_verdict(self) -> None:
        assert evaluate_safety(verdict_status=None) is None

    def test_invalid_string_verdict_returns_none(self) -> None:
        assert evaluate_safety(verdict_status="nonsense") is None

    def test_non_looping_verdicts_do_not_terminate(self) -> None:
        for status in (
            VerdictStatus.HEALTHY,
            VerdictStatus.STALLED,
            VerdictStatus.GOAL_DRIFT,
            VerdictStatus.BUDGET_RISK,
        ):
            assert evaluate_safety(verdict_status=status) is None, status

    def test_looping_fires_safety_looping(self) -> None:
        d = evaluate_safety(verdict_status=VerdictStatus.LOOPING, verdict_rationale="loop x3")
        assert d is not None
        assert d.reason is TerminationReason.SAFETY_LOOPING
        assert d.rationale == "loop x3"

    def test_looping_plus_doom_loop_fires_doom_loop(self) -> None:
        d = evaluate_safety(
            verdict_status=VerdictStatus.LOOPING,
            doom_loop_triggered=True,
        )
        assert d is not None
        assert d.reason is TerminationReason.SAFETY_DOOM_LOOP

    def test_string_verdict_accepted(self) -> None:
        d = evaluate_safety(verdict_status="looping")
        assert d is not None
        assert d.reason is TerminationReason.SAFETY_LOOPING


class TestTerminationDecision:
    def test_user_cancel_factory(self) -> None:
        d = TerminationDecision.user_cancel(rationale="explicit DELETE")
        assert d.reason is TerminationReason.USER_CANCEL
        assert d.actor == "user"
        assert d.gate == "user"
