"""Deterministic tenant and project rollout bucketing."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable


def parse_rollout_allowlist(raw: str | None) -> frozenset[str]:
    """Parse a comma-separated allowlist without retaining empty values."""
    if not raw:
        return frozenset()
    return frozenset(item.strip() for item in raw.split(",") if item.strip())


def rollout_bucket(capability: str, scope_id: str) -> int:
    """Return a stable bucket from 0 through 9,999 for one scope."""
    digest = hashlib.sha256(f"memstack-plugin-rollout:{capability}:{scope_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 10_000


def is_scope_selected(
    *,
    capability: str,
    scope_id: str | None,
    percentage: int,
    allowlist: Iterable[str] = (),
) -> bool:
    """Return whether this scope belongs to the staged rollout cohort."""
    normalized = (scope_id or "global").strip()
    if normalized in allowlist:
        return True
    bounded = max(0, min(100, percentage))
    return rollout_bucket(capability, normalized) < bounded * 100


def settings_percentage(settings: object, name: str) -> int:
    return max(0, min(100, int(getattr(settings, name))))


def settings_allowlist(settings: object, name: str) -> frozenset[str]:
    return parse_rollout_allowlist(getattr(settings, name, None))
