"""Temporal decay for search scores.

Ported from Moltbot's temporal-decay.ts.
Applies exponential decay based on document age.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime


def decay_lambda(half_life_days: float) -> float:
    """Compute decay constant from half-life in days.

    After half_life_days, the multiplier will be 0.5.
    """
    if half_life_days <= 0:
        return 0.0
    return math.log(2) / half_life_days


def temporal_decay_multiplier(
    age_days: float,
    half_life_days: float = 30.0,
) -> float:
    """Calculate the temporal decay multiplier for a given age.

    Args:
        age_days: Age of the document in days.
        half_life_days: Number of days until score decays to 50%.

    Returns:
        Multiplier in (0, 1] range.
    """
    if age_days <= 0:
        return 1.0
    lam = decay_lambda(half_life_days)
    return math.exp(-lam * age_days)


def apply_temporal_decay(
    score: float,
    created_at: datetime,
    half_life_days: float = 30.0,
    now: datetime | None = None,
) -> float:
    """Apply temporal decay to a search score.

    Args:
        score: Original relevance score.
        created_at: When the content was created.
        half_life_days: Decay half-life in days.
        now: Current time (defaults to utcnow).

    Returns:
        Decayed score.
    """
    if now is None:
        now = datetime.now(UTC)

    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)

    age_seconds = (now - created_at).total_seconds()
    age_days = max(0, age_seconds / 86400)

    return score * temporal_decay_multiplier(age_days, half_life_days)
