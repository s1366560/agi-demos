"""Pending review value object (Track B P2-3 phase-2).

A ``PendingReview`` materializes when a HITL request resolves to
``BLOCKING_HUMAN_ONLY`` — either because the agent declared that
category, or because the structural upgrade rule fired (see
``hitl_policy.resolve_hitl_policy``). The conversation may be
suspended until a human resolves it.

The value object is pure domain data; the storage adapter lives in
``src/infrastructure/adapters/secondary/persistence/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any

__all__ = ["PendingReview", "PendingReviewStatus"]


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PendingReviewStatus(str, Enum):
    """Lifecycle of a pending review."""

    OPEN = "open"
    RESOLVED = "resolved"
    WITHDRAWN = "withdrawn"  # agent retracted
    CANCELLED = "cancelled"  # conversation ended before resolution


@dataclass
class PendingReview:
    """A blocking HITL request queued for human action.

    Attributes:
        id: Primary key.
        conversation_id: Scope.
        scope_agent_id: The agent that raised the request (always
            non-null per p2-decisions).
        effective_category: Category after structural upgrade.
        declared_category: Category the agent originally declared (may
            differ from ``effective_category``).
        visibility: ``private`` | ``room``.
        urgency: ``normal`` | ``high`` | ``blocking``.
        question: Prose question from the agent.
        context: Optional prose context.
        rationale: Why the agent raised the request (Agent First audit).
        proposed_fallback: Optional prose describing what the agent
            would do if no human answers.
        status: Lifecycle state.
        created_at / resolved_at: Timestamps.
        resolution_payload: Human's response (free-form dict).
        structurally_upgraded: True iff the structural
            ``blocking_categories ∩ side_effects`` rule forced the
            upgrade to ``BLOCKING_HUMAN_ONLY``.
        metadata: Optional extras (tool name, side_effects, etc.).
    """

    conversation_id: str
    scope_agent_id: str
    effective_category: str
    declared_category: str
    visibility: str
    question: str
    id: str = ""
    urgency: str = "normal"
    context: str = ""
    rationale: str = ""
    proposed_fallback: str = ""
    status: PendingReviewStatus = PendingReviewStatus.OPEN
    created_at: datetime = field(default_factory=_utcnow)
    resolved_at: datetime | None = None
    resolution_payload: dict[str, Any] | None = None
    structurally_upgraded: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
