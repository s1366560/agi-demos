"""Scheduled session reset service.

Provides a stateless evaluator that determines whether a session should be
reset based on the agent's SessionPolicy. The actual scheduling infrastructure
(cron, asyncio tasks, etc.) calls this to make reset decisions.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from src.domain.model.agent.session_policy import SessionPolicy

logger = logging.getLogger(__name__)


class SessionResetScheduler:
    """Evaluates whether a session should be reset based on agent policy.

    This is a stateless evaluator — the actual scheduling infrastructure
    (cron, celery beat, etc.) calls this to decide whether to reset.
    """

    @staticmethod
    def should_reset(
        policy: SessionPolicy,
        last_activity_at: datetime | None,
        session_created_at: datetime | None,
        now: datetime | None = None,
    ) -> bool:
        """Determine if session should be reset based on policy.

        Args:
            policy: The agent's session policy.
            last_activity_at: When the session was last active.
            session_created_at: When the session was created.
            now: Current time (defaults to UTC now).

        Returns:
            True if the session should be reset.
        """
        if now is None:
            now = datetime.now(UTC)

        if _check_idle_timeout(policy, last_activity_at, now):
            return True

        if _check_daily_reset(policy, session_created_at, now):
            return True

        return _check_session_ttl(policy, session_created_at, now)


def _check_idle_timeout(
    policy: SessionPolicy,
    last_activity_at: datetime | None,
    now: datetime,
) -> bool:
    """Check if session has been idle beyond the threshold."""
    if policy.idle_reset_minutes is None or last_activity_at is None:
        return False

    idle_minutes = (now - last_activity_at).total_seconds() / 60
    if idle_minutes >= policy.idle_reset_minutes:
        logger.debug(
            "Session idle for %.1f minutes (threshold: %d)",
            idle_minutes,
            policy.idle_reset_minutes,
        )
        return True
    return False


def _check_daily_reset(
    policy: SessionPolicy,
    session_created_at: datetime | None,
    now: datetime,
) -> bool:
    """Check if daily reset hour has been reached."""
    if policy.daily_reset_hour is None or session_created_at is None:
        return False

    # Reset if current hour matches AND session was created before today
    if now.hour == policy.daily_reset_hour:
        session_date = session_created_at.date()
        if session_date < now.date():
            logger.debug(
                "Daily reset triggered at hour %d",
                policy.daily_reset_hour,
            )
            return True
    return False


def _check_session_ttl(
    policy: SessionPolicy,
    session_created_at: datetime | None,
    now: datetime,
) -> bool:
    """Check if session has exceeded its TTL."""
    if policy.session_ttl_hours is None or session_created_at is None:
        return False

    age_hours = (now - session_created_at).total_seconds() / 3600
    if age_hours >= policy.session_ttl_hours:
        logger.debug(
            "Session TTL exceeded: %.1f hours (max: %d)",
            age_hours,
            policy.session_ttl_hours,
        )
        return True
    return False
