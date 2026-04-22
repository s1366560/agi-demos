"""Supervisor verdict status enum (Track B P2-3 phase-2).

A ``SupervisorVerdict`` is the Supervisor agent's report on the health of
a multi-agent conversation.  The enum lists the five **structural** verdict
buckets the coordinator may act on:

- ``HEALTHY``      : conversation is progressing; no intervention required.
- ``STALLED``      : no measurable progress within the stale window.
- ``LOOPING``      : doom-loop counter exceeded threshold — agents are
                     repeating tool-calls without progress.
- ``GOAL_DRIFT``   : agents are working on something misaligned with the
                     ``goal_contract.primary_goal``.
- ``BUDGET_RISK``  : projected budget spend > ``goal_contract.budget`` cap.

Agent First:
    The MAPPING (signals → verdict) is a subjective judgment made by the
    Supervisor **Agent**.  Structural trigger predicates in the scheduler
    only surface *signals* (elapsed time, counters, cost math) — they never
    classify health themselves.
"""

from __future__ import annotations

from enum import Enum


class VerdictStatus(str, Enum):
    """Supervisor verdict outcomes."""

    HEALTHY = "healthy"
    STALLED = "stalled"
    LOOPING = "looping"
    GOAL_DRIFT = "goal_drift"
    BUDGET_RISK = "budget_risk"

    @property
    def is_actionable(self) -> bool:
        """Whether this verdict requires coordinator intervention."""
        return self != VerdictStatus.HEALTHY
