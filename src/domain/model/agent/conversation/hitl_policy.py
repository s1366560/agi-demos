"""Human-in-the-loop (HITL) policy (Track B P2-3 phase-2).

The HITL category is **declared by the requesting agent** via
``request_human_input`` (Agent First); this module only implements the
*structural* pieces:

- ``HitlCategory`` / ``HitlVisibility`` enums.
- ``resolve_hitl_visibility(mode)``: visibility follows conversation mode.
- Structural upgrade: if the tool's ``side_effects`` intersect the goal's
  ``blocking_categories``, the request is **forced** to
  ``BLOCKING_HUMAN_ONLY`` regardless of the agent's declared category.
  This intersection test is a protocol fact — not a judgment.

No natural-language classification happens here.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum

from src.domain.model.agent.conversation.conversation_mode import ConversationMode

__all__ = [
    "HitlCategory",
    "HitlPolicyDecision",
    "HitlVisibility",
    "resolve_hitl_policy",
    "resolve_hitl_visibility",
]


class HitlCategory(str, Enum):
    """Three-tier HITL classification declared by the requesting agent."""

    BLOCKING_HUMAN_ONLY = "blocking_human_only"
    PREFERENCE = "preference"
    INFORMATIONAL = "informational"

    @property
    def blocks_conversation(self) -> bool:
        return self is HitlCategory.BLOCKING_HUMAN_ONLY


class HitlVisibility(str, Enum):
    """Where the HITL request is visible."""

    PRIVATE = "private"  # scope_agent_id ⟷ user
    ROOM = "room"  # visible to all participants


@dataclass(frozen=True)
class HitlPolicyDecision:
    """Structural outcome of applying HITL policy to a single request.

    Attributes:
        declared_category: What the agent said.
        effective_category: What the protocol enforces (may differ if
            the structural upgrade fired).
        visibility: Derived from conversation mode.
        structurally_upgraded: True iff ``blocking_categories ∩
            side_effects`` forced ``BLOCKING_HUMAN_ONLY``.
        blocking_intersection: The set of categories that caused the
            upgrade (empty if no upgrade).
    """

    declared_category: HitlCategory
    effective_category: HitlCategory
    visibility: HitlVisibility
    structurally_upgraded: bool
    blocking_intersection: frozenset[str]


_ROOM_MODES: frozenset[ConversationMode] = frozenset(
    {ConversationMode.MULTI_AGENT_SHARED, ConversationMode.AUTONOMOUS}
)


def resolve_hitl_visibility(mode: ConversationMode) -> HitlVisibility:
    """single / isolated → private; shared / autonomous → room."""
    if mode in _ROOM_MODES:
        return HitlVisibility.ROOM
    return HitlVisibility.PRIVATE


def resolve_hitl_policy(
    *,
    declared_category: HitlCategory,
    mode: ConversationMode,
    tool_side_effects: Iterable[str] | None,
    blocking_categories: Iterable[str] | None,
) -> HitlPolicyDecision:
    """Apply the HITL policy to one request.

    Rule 1 (visibility): ``resolve_hitl_visibility(mode)``.
    Rule 2 (structural upgrade): if ``blocking_categories ∩
    tool_side_effects ≠ ∅`` then ``effective_category =
    BLOCKING_HUMAN_ONLY`` regardless of ``declared_category``.
    Otherwise ``effective_category = declared_category``.
    """
    side_effects = frozenset(tool_side_effects or ())
    blocking = frozenset(blocking_categories or ())
    intersection = side_effects & blocking

    if intersection:
        return HitlPolicyDecision(
            declared_category=declared_category,
            effective_category=HitlCategory.BLOCKING_HUMAN_ONLY,
            visibility=resolve_hitl_visibility(mode),
            structurally_upgraded=declared_category is not HitlCategory.BLOCKING_HUMAN_ONLY,
            blocking_intersection=intersection,
        )

    return HitlPolicyDecision(
        declared_category=declared_category,
        effective_category=declared_category,
        visibility=resolve_hitl_visibility(mode),
        structurally_upgraded=False,
        blocking_intersection=frozenset(),
    )
