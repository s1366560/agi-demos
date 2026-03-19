"""Tests for Phase 3 domain value objects and enums (Context & Routing)."""

import dataclasses

import pytest

from src.domain.model.agent.assembled_context import AssembledContext
from src.domain.model.agent.binding_scope import BindingScope
from src.domain.model.agent.context_segment import ContextSegment
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.model.agent.dependency_type import DependencyType
from src.domain.model.agent.merge_strategy import MergeStrategy
from src.domain.model.agent.message_binding import MessageBinding


@pytest.mark.unit
class TestMergeStrategy:
    def test_values(self) -> None:
        assert MergeStrategy.RESULT_ONLY == "result_only"
        assert MergeStrategy.FULL_HISTORY == "full_history"
        assert MergeStrategy.SUMMARY == "summary"

    def test_is_str_enum(self) -> None:
        assert isinstance(MergeStrategy.RESULT_ONLY, str)

    def test_all_members(self) -> None:
        assert set(MergeStrategy) == {
            MergeStrategy.RESULT_ONLY,
            MergeStrategy.FULL_HISTORY,
            MergeStrategy.SUMMARY,
        }


@pytest.mark.unit
class TestBindingScope:
    def test_values(self) -> None:
        assert BindingScope.CONVERSATION == "conversation"
        assert BindingScope.USER_AGENT == "user_agent"
        assert BindingScope.PROJECT_ROLE == "project_role"
        assert BindingScope.PROJECT == "project"
        assert BindingScope.TENANT == "tenant"
        assert BindingScope.DEFAULT == "default"

    def test_priority_ordering(self) -> None:
        assert BindingScope.CONVERSATION.priority < BindingScope.USER_AGENT.priority
        assert BindingScope.USER_AGENT.priority < BindingScope.PROJECT_ROLE.priority
        assert BindingScope.PROJECT_ROLE.priority < BindingScope.PROJECT.priority
        assert BindingScope.PROJECT.priority < BindingScope.TENANT.priority
        assert BindingScope.TENANT.priority < BindingScope.DEFAULT.priority

    def test_conversation_highest_priority(self) -> None:
        assert BindingScope.CONVERSATION.priority == 0

    def test_default_lowest_priority(self) -> None:
        assert BindingScope.DEFAULT.priority == 5

    def test_is_str_enum(self) -> None:
        assert isinstance(BindingScope.CONVERSATION, str)

    def test_all_members_count(self) -> None:
        assert len(BindingScope) == 6


@pytest.mark.unit
class TestDependencyType:
    def test_values(self) -> None:
        assert DependencyType.HARD == "hard"
        assert DependencyType.SOFT == "soft"
        assert DependencyType.STREAMING == "streaming"

    def test_is_str_enum(self) -> None:
        assert isinstance(DependencyType.HARD, str)

    def test_all_members(self) -> None:
        assert set(DependencyType) == {
            DependencyType.HARD,
            DependencyType.SOFT,
            DependencyType.STREAMING,
        }


@pytest.mark.unit
class TestContextSegment:
    def test_create_minimal(self) -> None:
        seg = ContextSegment(source="memory", content="hello")

        assert seg.source == "memory"
        assert seg.content == "hello"
        assert seg.token_count == 0
        assert seg.metadata == {}

    def test_create_full(self) -> None:
        seg = ContextSegment(
            source="knowledge_graph",
            content="entity data",
            token_count=42,
            metadata={"node_id": "n1"},
        )

        assert seg.source == "knowledge_graph"
        assert seg.content == "entity data"
        assert seg.token_count == 42
        assert seg.metadata == {"node_id": "n1"}

    def test_frozen_immutability(self) -> None:
        seg = ContextSegment(source="memory", content="hello")

        with pytest.raises(dataclasses.FrozenInstanceError):
            seg.source = "other"  # type: ignore[misc]

    def test_empty_source_raises(self) -> None:
        with pytest.raises(ValueError, match="source must not be empty"):
            ContextSegment(source="", content="hello")

    def test_is_empty_true_for_empty_content(self) -> None:
        seg = ContextSegment(source="memory", content="")

        assert seg.is_empty is True

    def test_is_empty_false_for_nonempty_content(self) -> None:
        seg = ContextSegment(source="memory", content="data")

        assert seg.is_empty is False

    def test_equality_by_value(self) -> None:
        a = ContextSegment(source="memory", content="hello", token_count=10)
        b = ContextSegment(source="memory", content="hello", token_count=10)

        assert a == b

    def test_inequality_different_content(self) -> None:
        a = ContextSegment(source="memory", content="hello")
        b = ContextSegment(source="memory", content="world")

        assert a != b


@pytest.mark.unit
class TestAssembledContext:
    def _make_message(self, content: str = "test") -> Message:
        return Message(
            conversation_id="conv-1",
            role=MessageRole.USER,
            content=content,
            message_type=MessageType.TEXT,
        )

    def test_create_minimal(self) -> None:
        ctx = AssembledContext(system_prompt="You are helpful.")

        assert ctx.system_prompt == "You are helpful."
        assert ctx.messages == ()
        assert ctx.injected_context == ()
        assert ctx.total_tokens == 0
        assert ctx.budget_tokens == 0
        assert ctx.is_compacted is False

    def test_frozen_immutability(self) -> None:
        ctx = AssembledContext(system_prompt="test")

        with pytest.raises(dataclasses.FrozenInstanceError):
            ctx.system_prompt = "other"  # type: ignore[misc]

    def test_message_count(self) -> None:
        m1 = self._make_message("a")
        m2 = self._make_message("b")
        ctx = AssembledContext(system_prompt="sys", messages=(m1, m2))

        assert ctx.message_count == 2

    def test_segment_count(self) -> None:
        s1 = ContextSegment(source="memory", content="x")
        s2 = ContextSegment(source="graph", content="y")
        ctx = AssembledContext(system_prompt="sys", injected_context=(s1, s2))

        assert ctx.segment_count == 2

    def test_is_over_budget_true(self) -> None:
        ctx = AssembledContext(
            system_prompt="sys",
            total_tokens=5000,
            budget_tokens=4000,
        )

        assert ctx.is_over_budget is True

    def test_is_over_budget_false_within_budget(self) -> None:
        ctx = AssembledContext(
            system_prompt="sys",
            total_tokens=3000,
            budget_tokens=4000,
        )

        assert ctx.is_over_budget is False

    def test_is_over_budget_false_zero_budget(self) -> None:
        ctx = AssembledContext(
            system_prompt="sys",
            total_tokens=5000,
            budget_tokens=0,
        )

        assert ctx.is_over_budget is False

    def test_with_compacted_returns_new_context(self) -> None:
        m1 = self._make_message("original")
        m2 = self._make_message("compacted")
        seg = ContextSegment(source="memory", content="data")

        original = AssembledContext(
            system_prompt="sys",
            messages=(m1,),
            injected_context=(seg,),
            total_tokens=5000,
            budget_tokens=4000,
        )

        compacted = original.with_compacted(messages=(m2,), total_tokens=3000)

        assert compacted is not original
        assert compacted.system_prompt == "sys"
        assert compacted.messages == (m2,)
        assert compacted.injected_context == (seg,)
        assert compacted.total_tokens == 3000
        assert compacted.budget_tokens == 4000
        assert compacted.is_compacted is True

    def test_with_compacted_preserves_original(self) -> None:
        m1 = self._make_message("original")

        original = AssembledContext(
            system_prompt="sys",
            messages=(m1,),
            total_tokens=5000,
            budget_tokens=4000,
        )

        original.with_compacted(messages=(), total_tokens=0)

        assert original.messages == (m1,)
        assert original.total_tokens == 5000
        assert original.is_compacted is False


@pytest.mark.unit
class TestMessageBinding:
    def test_create_minimal(self) -> None:
        binding = MessageBinding(agent_id="agent-1")

        assert binding.agent_id == "agent-1"
        assert binding.scope == BindingScope.DEFAULT
        assert binding.scope_id == ""
        assert binding.priority == 0
        assert binding.filter_pattern is None
        assert binding.is_active is True
        assert binding.id

    def test_frozen_immutability(self) -> None:
        binding = MessageBinding(agent_id="agent-1")

        with pytest.raises(dataclasses.FrozenInstanceError):
            binding.agent_id = "other"  # type: ignore[misc]

    def test_empty_agent_id_raises(self) -> None:
        with pytest.raises(ValueError, match="agent_id must not be empty"):
            MessageBinding(agent_id="")

    def test_matches_scope_active(self) -> None:
        binding = MessageBinding(
            agent_id="agent-1",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )

        assert binding.matches_scope(BindingScope.PROJECT, "proj-1") is True

    def test_matches_scope_wrong_scope(self) -> None:
        binding = MessageBinding(
            agent_id="agent-1",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )

        assert binding.matches_scope(BindingScope.TENANT, "proj-1") is False

    def test_matches_scope_wrong_scope_id(self) -> None:
        binding = MessageBinding(
            agent_id="agent-1",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
        )

        assert binding.matches_scope(BindingScope.PROJECT, "proj-2") is False

    def test_matches_scope_inactive(self) -> None:
        binding = MessageBinding(
            agent_id="agent-1",
            scope=BindingScope.PROJECT,
            scope_id="proj-1",
            is_active=False,
        )

        assert binding.matches_scope(BindingScope.PROJECT, "proj-1") is False

    def test_auto_generated_id_unique(self) -> None:
        b1 = MessageBinding(agent_id="agent-1")
        b2 = MessageBinding(agent_id="agent-1")

        assert b1.id != b2.id

    def test_timestamps_populated(self) -> None:
        binding = MessageBinding(agent_id="agent-1")

        assert binding.created_at is not None
        assert binding.updated_at is not None

    def test_custom_priority_and_filter(self) -> None:
        binding = MessageBinding(
            agent_id="agent-1",
            scope=BindingScope.CONVERSATION,
            scope_id="conv-1",
            priority=10,
            filter_pattern=r".*urgent.*",
        )

        assert binding.priority == 10
        assert binding.filter_pattern == r".*urgent.*"
