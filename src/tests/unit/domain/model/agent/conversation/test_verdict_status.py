"""Tests for VerdictStatus enum (Track B P2-3 phase-2)."""

from __future__ import annotations

from src.domain.model.agent.conversation.verdict_status import VerdictStatus


def test_enum_values_are_stable() -> None:
    values = {s.value for s in VerdictStatus}
    assert values == {
        "healthy",
        "stalled",
        "looping",
        "goal_drift",
        "budget_risk",
    }


def test_healthy_is_not_actionable() -> None:
    assert VerdictStatus.HEALTHY.is_actionable is False


def test_all_non_healthy_are_actionable() -> None:
    for status in VerdictStatus:
        if status is VerdictStatus.HEALTHY:
            continue
        assert status.is_actionable is True


def test_str_subclass_roundtrip() -> None:
    assert VerdictStatus("stalled") is VerdictStatus.STALLED
    assert VerdictStatus.STALLED == "stalled"
