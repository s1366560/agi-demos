"""Delivery readiness — branch / commit state pill for the Done lane.

Distilled from routa's "is this PR actually mergeable" indicator. The
agent or sandbox tool reports the structural facts (branch name, ahead /
behind, modified, untracked, commits since base). This module classifies
those facts into a small enum the UI can render as a colored pill.

Per Agent-First: classification thresholds (e.g. "behind > 0 = STALE") are
**structural** (arithmetic on integers), not subjective verdicts — they
stay deterministic. Whether a stale branch should *block* a release is a
subjective call and stays with an agent tool-call elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from src.domain.shared_kernel import ValueObject


class DeliveryReadiness(str, Enum):
    """High-level pill state."""

    READY = "ready"
    """No uncommitted changes, branch is up to date with base, ahead ≥ 1."""
    DIRTY = "dirty"
    """Uncommitted changes (modified or untracked) present."""
    STALE = "stale"
    """Behind base by ≥ 1 commit."""
    EMPTY = "empty"
    """No commits since base — nothing to deliver yet."""
    UNKNOWN = "unknown"
    """No data reported."""


@dataclass(frozen=True, kw_only=True)
class DeliveryStatus(ValueObject):
    """Structural snapshot reported by the sandbox/git tool."""

    branch: str
    base_branch: str = "main"
    ahead: int = 0
    behind: int = 0
    modified_files: tuple[str, ...] = field(default_factory=tuple)
    untracked_files: tuple[str, ...] = field(default_factory=tuple)
    commits_since_base: int = 0


@dataclass(frozen=True, kw_only=True)
class DeliveryReadinessReport(ValueObject):
    """Pure classification of a :class:`DeliveryStatus`."""

    status: DeliveryStatus
    readiness: DeliveryReadiness
    reason: str

    @property
    def is_ready(self) -> bool:
        return self.readiness is DeliveryReadiness.READY


def classify_delivery_readiness(
    status: DeliveryStatus | None,
) -> DeliveryReadinessReport:
    """Pure structural classification. Order: dirty > stale > empty > ready."""
    if status is None:
        return DeliveryReadinessReport(
            status=DeliveryStatus(branch=""),
            readiness=DeliveryReadiness.UNKNOWN,
            reason="No delivery status reported.",
        )

    has_dirty = bool(status.modified_files or status.untracked_files)
    if has_dirty:
        modified_count = len(status.modified_files)
        untracked_count = len(status.untracked_files)
        return DeliveryReadinessReport(
            status=status,
            readiness=DeliveryReadiness.DIRTY,
            reason=f"{modified_count} modified, {untracked_count} untracked",
        )
    if status.behind > 0:
        return DeliveryReadinessReport(
            status=status,
            readiness=DeliveryReadiness.STALE,
            reason=f"{status.behind} commit(s) behind {status.base_branch}",
        )
    if status.commits_since_base == 0 and status.ahead == 0:
        return DeliveryReadinessReport(
            status=status,
            readiness=DeliveryReadiness.EMPTY,
            reason="No commits since base.",
        )
    return DeliveryReadinessReport(
        status=status,
        readiness=DeliveryReadiness.READY,
        reason=f"{status.ahead} commit(s) ahead, clean tree.",
    )


__all__ = [
    "DeliveryReadiness",
    "DeliveryReadinessReport",
    "DeliveryStatus",
    "classify_delivery_readiness",
]
