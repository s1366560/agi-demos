"""Spawn policy value objects for SubAgent delegation control.

Defines constraints governing when and how SubAgents may be spawned,
including depth limits, concurrency caps, and allow-lists.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.domain.shared_kernel import ValueObject


class SpawnRejectionCode(str, Enum):
    """Categorised reason a spawn request was denied."""

    DEPTH_EXCEEDED = "depth_exceeded"
    CONCURRENCY_EXCEEDED = "concurrency_exceeded"
    CHILDREN_EXCEEDED = "children_exceeded"
    SUBAGENT_NOT_ALLOWED = "subagent_not_allowed"


@dataclass(frozen=True)
class SpawnPolicy(ValueObject):
    """Immutable policy governing SubAgent spawn behaviour.

    Attributes:
        max_depth: Maximum delegation depth (0 = no nesting).
        max_active_runs: Global cap on concurrent SubAgent runs.
        max_children_per_requester: Per-parent cap on active children.
        allowed_subagents: Explicit allow-list; ``None`` permits all.
    """

    max_depth: int = 2
    max_active_runs: int = 16
    max_children_per_requester: int = 8
    allowed_subagents: frozenset[str] | None = None

    def __post_init__(self) -> None:
        if self.max_depth < 0:
            raise ValueError(f"max_depth must be >= 0, got {self.max_depth}")
        if self.max_active_runs < 1:
            raise ValueError(f"max_active_runs must be >= 1, got {self.max_active_runs}")
        if self.max_children_per_requester < 1:
            raise ValueError(
                f"max_children_per_requester must be >= 1, got {self.max_children_per_requester}"
            )

    @classmethod
    def from_settings(cls, settings: object) -> SpawnPolicy:
        """Construct from an application settings object.

        Reads attributes ``AGENT_SUBAGENT_MAX_DELEGATION_DEPTH``,
        ``AGENT_SUBAGENT_MAX_ACTIVE_RUNS``,
        ``AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER``, and
        ``AGENT_SUBAGENT_ALLOWED_SUBAGENTS``.
        Falls back to dataclass defaults when attributes are absent.
        """
        raw_allowed: list[str] | frozenset[str] | None = getattr(
            settings, "AGENT_SUBAGENT_ALLOWED_SUBAGENTS", None
        )
        allowed: frozenset[str] | None = frozenset(raw_allowed) if raw_allowed is not None else None
        return cls(
            max_depth=getattr(settings, "AGENT_SUBAGENT_MAX_DELEGATION_DEPTH", 2),
            max_active_runs=getattr(settings, "AGENT_SUBAGENT_MAX_ACTIVE_RUNS", 16),
            max_children_per_requester=getattr(
                settings, "AGENT_SUBAGENT_MAX_CHILDREN_PER_REQUESTER", 8
            ),
            allowed_subagents=allowed,
        )


@dataclass(frozen=True)
class SpawnValidationResult(ValueObject):
    """Outcome of a spawn-eligibility check.

    Attributes:
        allowed: Whether the spawn is permitted.
        rejection_reason: Human-readable explanation (``None`` when allowed).
        rejection_code: Machine-readable code (``None`` when allowed).
        context: Diagnostic key-value pairs for logging / debugging.
    """

    allowed: bool
    rejection_reason: str | None = None
    rejection_code: SpawnRejectionCode | None = None
    context: dict[str, Any] = field(default_factory=lambda: dict[str, Any]())

    @staticmethod
    def ok() -> SpawnValidationResult:
        """Factory for an *allowed* result."""
        return SpawnValidationResult(allowed=True)

    @staticmethod
    def rejected(
        reason: str,
        code: SpawnRejectionCode,
        context: dict[str, Any] | None = None,
    ) -> SpawnValidationResult:
        """Factory for a *rejected* result."""
        return SpawnValidationResult(
            allowed=False,
            rejection_reason=reason,
            rejection_code=code,
            context=context if context is not None else {},
        )
