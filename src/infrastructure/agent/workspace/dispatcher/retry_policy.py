"""Dispatcher retry policy (P2d M2 — minimal stub).

Placeholder for future work. M2 does not yet consolidate retry/backoff logic
(which currently lives in ``_schedule_workspace_retry_attempt`` and elsewhere).
This module exists to mark the extension point so M4 / M5 refactors have a
clear target.

The constants here are intentionally set to permissive defaults; callers that
want to enforce a retry budget must opt in.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = ["DEFAULT_RETRY_POLICY", "DispatchRetryPolicy"]


@dataclass(frozen=True)
class DispatchRetryPolicy:
    """Policy parameters for future retry/backoff logic.

    Attributes
    ----------
    max_attempts:
        Maximum number of times an execution task may be dispatched before the
        dispatcher gives up and signals "replan required" upstream. Must be >= 1.
    initial_backoff_seconds:
        Backoff before the *second* dispatch. Exponentially doubled for
        subsequent attempts, capped at ``max_backoff_seconds``.
    max_backoff_seconds:
        Upper bound on backoff between dispatch attempts.
    """

    max_attempts: int = 3
    initial_backoff_seconds: float = 5.0
    max_backoff_seconds: float = 120.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if self.initial_backoff_seconds < 0:
            raise ValueError("initial_backoff_seconds must be >= 0")
        if self.max_backoff_seconds < self.initial_backoff_seconds:
            raise ValueError("max_backoff_seconds must be >= initial_backoff_seconds")

    def backoff_for(self, attempt: int) -> float:
        """Return the backoff for ``attempt`` (1-indexed; attempt=1 → 0s)."""
        if attempt <= 1:
            return 0.0
        # Exponential: initial * 2^(attempt-2), capped.
        value = self.initial_backoff_seconds * (2 ** (attempt - 2))
        return min(value, self.max_backoff_seconds)


DEFAULT_RETRY_POLICY = DispatchRetryPolicy()
