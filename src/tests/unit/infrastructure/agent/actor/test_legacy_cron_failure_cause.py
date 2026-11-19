"""A fail-closed judge code stays on the cron terminal."""

from __future__ import annotations

from typing import Any

import pytest

from src.infrastructure.agent.actor import legacy_cron_admission


@pytest.mark.unit
async def test_goal_judge_event_fails_the_stream_with_its_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _complete(identity: object, outcome: str, *, cause: str | None = None) -> None:
        seen["identity"] = identity
        seen["outcome"] = outcome
        seen["cause"] = cause

    monkeypatch.setattr(legacy_cron_admission, "complete_legacy_cron_admission", _complete)
    ticket = object()
    await legacy_cron_admission.complete_legacy_cron_stream(
        ticket,
        [
            {"type": "error", "data": {"code": "GOAL_JUDGE_UNAVAILABLE"}},
            {"type": "complete", "data": {}},
        ],
        False,
    )
    assert seen == {
        "identity": ticket,
        "outcome": "failed",
        "cause": "GOAL_JUDGE_UNAVAILABLE",
    }
