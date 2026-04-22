"""Tests for ``hitl_policy`` (Track B P2-3 phase-2)."""

from __future__ import annotations

import pytest

from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.hitl_policy import (
    HitlCategory,
    HitlPolicyDecision,
    HitlVisibility,
    resolve_hitl_policy,
    resolve_hitl_visibility,
)


class TestVisibility:
    @pytest.mark.parametrize(
        ("mode", "expected"),
        [
            (ConversationMode.SINGLE_AGENT, HitlVisibility.PRIVATE),
            (ConversationMode.MULTI_AGENT_ISOLATED, HitlVisibility.PRIVATE),
            (ConversationMode.MULTI_AGENT_SHARED, HitlVisibility.ROOM),
            (ConversationMode.AUTONOMOUS, HitlVisibility.ROOM),
        ],
    )
    def test_visibility_by_mode(self, mode: ConversationMode, expected: HitlVisibility) -> None:
        assert resolve_hitl_visibility(mode) is expected


class TestStructuralUpgrade:
    def test_no_intersection_keeps_declared_category(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.PREFERENCE,
            mode=ConversationMode.AUTONOMOUS,
            tool_side_effects=["read"],
            blocking_categories=["irreversible", "pii"],
        )
        assert isinstance(decision, HitlPolicyDecision)
        assert decision.effective_category is HitlCategory.PREFERENCE
        assert decision.declared_category is HitlCategory.PREFERENCE
        assert decision.structurally_upgraded is False
        assert decision.blocking_intersection == frozenset()
        assert decision.visibility is HitlVisibility.ROOM

    def test_intersection_forces_blocking(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.INFORMATIONAL,
            mode=ConversationMode.SINGLE_AGENT,
            tool_side_effects=["irreversible", "write"],
            blocking_categories=["irreversible"],
        )
        assert decision.effective_category is HitlCategory.BLOCKING_HUMAN_ONLY
        assert decision.declared_category is HitlCategory.INFORMATIONAL
        assert decision.structurally_upgraded is True
        assert decision.blocking_intersection == frozenset({"irreversible"})
        assert decision.visibility is HitlVisibility.PRIVATE

    def test_already_blocking_is_not_flagged_as_upgraded(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.BLOCKING_HUMAN_ONLY,
            mode=ConversationMode.MULTI_AGENT_SHARED,
            tool_side_effects=["irreversible"],
            blocking_categories=["irreversible", "pii"],
        )
        assert decision.effective_category is HitlCategory.BLOCKING_HUMAN_ONLY
        assert decision.structurally_upgraded is False
        assert decision.blocking_intersection == frozenset({"irreversible"})

    def test_none_iterables_behave_as_empty(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.PREFERENCE,
            mode=ConversationMode.MULTI_AGENT_ISOLATED,
            tool_side_effects=None,
            blocking_categories=None,
        )
        assert decision.effective_category is HitlCategory.PREFERENCE
        assert decision.structurally_upgraded is False
        assert decision.blocking_intersection == frozenset()

    def test_multiple_intersection_preserved(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.INFORMATIONAL,
            mode=ConversationMode.AUTONOMOUS,
            tool_side_effects=["irreversible", "pii", "network"],
            blocking_categories=["irreversible", "pii"],
        )
        assert decision.structurally_upgraded is True
        assert decision.blocking_intersection == frozenset({"irreversible", "pii"})

    def test_decision_is_frozen(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.PREFERENCE,
            mode=ConversationMode.SINGLE_AGENT,
            tool_side_effects=[],
            blocking_categories=[],
        )
        with pytest.raises(Exception):  # dataclass FrozenInstanceError
            decision.effective_category = HitlCategory.INFORMATIONAL  # type: ignore[misc]
