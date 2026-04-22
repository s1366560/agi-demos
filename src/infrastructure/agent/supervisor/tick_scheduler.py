"""Supervisor tick scheduler (Track B P2-3 phase-2).

Supervisor agents are woken by *structural* signals — not by content
inspection.  This module exposes three pure predicate functions plus a
small stateful scheduler that decides when to enqueue a "supervisor tick"
message on an active conversation.

Agent First:
    All logic here is pure math over timestamps and counters.  The
    Supervisor Agent receives these signals through a system-style prompt
    (built by the coordinator) and MUST interpret them into a verdict
    itself — there is no keyword matching or NLP here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import Enum

__all__ = [
    "SupervisorTickState",
    "TickDecision",
    "TickTrigger",
    "decide",
    "should_breakloop",
    "should_budget_risk",
    "should_stale",
    "should_tick",
]


class TickTrigger(str, Enum):
    """Which structural signal fired the tick."""

    NONE = "none"
    TICK = "tick"
    STALE = "stale"
    DOOM_LOOP = "doom_loop"
    BUDGET = "budget"


@dataclass(frozen=True)
class TickDecision:
    """Structural decision surface passed to the Supervisor agent."""

    should_fire: bool
    trigger: TickTrigger
    signals: dict[str, str] = field(default_factory=dict)


@dataclass
class SupervisorTickState:
    """Per-conversation scheduler state."""

    conversation_id: str
    last_tick_at: datetime | None = None


def _utcnow() -> datetime:
    return datetime.now(UTC)


def should_tick(
    last_tick_at: datetime | None,
    tick_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Periodic tick: fire every ``tick_seconds``."""
    if tick_seconds <= 0:
        return False
    current = now or _utcnow()
    if last_tick_at is None:
        return True
    elapsed = current - last_tick_at
    return elapsed >= timedelta(seconds=tick_seconds)


def should_stale(
    last_progress_at: datetime | None,
    stale_threshold_seconds: int,
    now: datetime | None = None,
) -> bool:
    """Progress staleness: fire if no declare_progress within threshold."""
    if stale_threshold_seconds <= 0:
        return False
    if last_progress_at is None:
        return False
    current = now or _utcnow()
    return (current - last_progress_at) >= timedelta(seconds=stale_threshold_seconds)


def should_breakloop(doom_loop_counter: int, max_loops: int) -> bool:
    """Doom-loop: fire when detector counter >= threshold."""
    if max_loops <= 0:
        return False
    return doom_loop_counter >= max_loops


def should_budget_risk(
    projected_spend: float,
    budget_cap: float,
    warn_ratio: float = 0.9,
) -> bool:
    """Budget risk: fire when projected spend exceeds ``warn_ratio * cap``."""
    if budget_cap <= 0:
        return False
    if warn_ratio <= 0:
        return False
    return projected_spend >= (budget_cap * warn_ratio)


def decide(
    state: SupervisorTickState,
    *,
    tick_seconds: int,
    stale_threshold_seconds: int,
    doom_loop_counter: int,
    max_loops: int,
    projected_spend: float = 0.0,
    budget_cap: float = 0.0,
    last_progress_at: datetime | None = None,
    now: datetime | None = None,
) -> TickDecision:
    """Compute whether to solicit a verdict from the Supervisor.

    Priority order (first match wins):
        1. DOOM_LOOP
        2. STALE
        3. BUDGET
        4. TICK
    """
    current = now or _utcnow()
    signals: dict[str, str] = {
        "doom_loop_counter": str(doom_loop_counter),
        "doom_loop_threshold": str(max_loops),
        "projected_spend": f"{projected_spend:.4f}",
        "budget_cap": f"{budget_cap:.4f}",
        "tick_seconds": str(tick_seconds),
        "stale_threshold_seconds": str(stale_threshold_seconds),
    }
    if last_progress_at is not None:
        signals["last_progress_at"] = last_progress_at.isoformat()
        signals["seconds_since_progress"] = str(int((current - last_progress_at).total_seconds()))
    if state.last_tick_at is not None:
        signals["last_tick_at"] = state.last_tick_at.isoformat()
        signals["seconds_since_tick"] = str(int((current - state.last_tick_at).total_seconds()))

    if should_breakloop(doom_loop_counter, max_loops):
        return TickDecision(True, TickTrigger.DOOM_LOOP, signals)
    if should_stale(last_progress_at, stale_threshold_seconds, now=current):
        return TickDecision(True, TickTrigger.STALE, signals)
    if should_budget_risk(projected_spend, budget_cap):
        return TickDecision(True, TickTrigger.BUDGET, signals)
    if should_tick(state.last_tick_at, tick_seconds, now=current):
        return TickDecision(True, TickTrigger.TICK, signals)
    return TickDecision(False, TickTrigger.NONE, signals)
