"""Tests for Phase 3 Wave 6: SessionForkMerge integration.

End-to-end tests validating the fork->execute->merge lifecycle using
SessionForkMergeService with all three MergeStrategy variants.
"""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import SessionForkedEvent, SessionMergedEvent
from src.domain.model.agent.conversation.conversation import Conversation
from src.domain.model.agent.merge_strategy import MergeStrategy
from src.domain.model.agent.subagent_result import SubAgentResult
from src.infrastructure.agent.subagent.session_fork_merge_service import (
    SessionForkMergeService,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_parent(
    *,
    conv_id: str = "parent-1",
    project_id: str = "proj-1",
    tenant_id: str = "t-1",
    user_id: str = "user-1",
) -> Conversation:
    return Conversation(
        id=conv_id,
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
        title="Parent conversation",
    )


def _make_result(
    *,
    success: bool = True,
    summary: str = "Done",
    name: str = "worker",
    tool_calls: int = 5,
    tokens: int = 800,
    error: str | None = None,
) -> SubAgentResult:
    return SubAgentResult(
        subagent_id="sa-1",
        subagent_name=name,
        summary=summary,
        success=success,
        tool_calls_count=tool_calls,
        tokens_used=tokens,
        error=error,
    )


@pytest.fixture()
def service() -> SessionForkMergeService:
    return SessionForkMergeService()


# ---------------------------------------------------------------------------
# Full fork -> merge round-trip (RESULT_ONLY)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForkMergeResultOnly:
    async def test_round_trip_success(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, fork_evt = await service.fork_session(
            parent,
            user_id="user-2",
            title="Research subtask",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            context_snapshot="snapshot-data",
        )
        result = _make_result(summary="Research complete")
        merged, merge_evt = await service.merge_session(parent, child, result)

        assert isinstance(fork_evt, SessionForkedEvent)
        assert isinstance(merge_evt, SessionMergedEvent)
        assert fork_evt.child_conversation_id == child.id
        assert merge_evt.merge_strategy == "result_only"
        assert "completed successfully" in merged
        assert "Research complete" in merged

    async def test_round_trip_failure(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Failing subtask",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        result = _make_result(success=False, summary="Partial", error="Timeout", name="builder")
        merged, merge_evt = await service.merge_session(parent, child, result)

        assert "failed" in merged
        assert "Timeout" in merged
        assert merge_evt.merge_strategy == "result_only"


# ---------------------------------------------------------------------------
# Full fork -> merge round-trip (FULL_HISTORY)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForkMergeFullHistory:
    async def test_round_trip_with_messages(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, fork_evt = await service.fork_session(
            parent,
            user_id="user-2",
            title="Deep analysis",
            merge_strategy=MergeStrategy.FULL_HISTORY,
        )
        result = _make_result(summary="Analysis done")
        messages = ["Step 1: gathered data", "Step 2: analyzed patterns"]
        merged, merge_evt = await service.merge_session(
            parent, child, result, child_messages=messages
        )

        assert fork_evt.parent_conversation_id == parent.id
        assert merge_evt.merge_strategy == "full_history"
        assert "Deep analysis" in merged
        assert "Step 1: gathered data" in merged
        assert "Step 2: analyzed patterns" in merged
        assert "---" in merged

    async def test_round_trip_empty_messages(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Empty subtask",
            merge_strategy=MergeStrategy.FULL_HISTORY,
        )
        result = _make_result()
        merged, _ = await service.merge_session(parent, child, result)

        assert "No messages recorded" in merged


# ---------------------------------------------------------------------------
# Full fork -> merge round-trip (SUMMARY)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForkMergeSummary:
    async def test_round_trip_uses_summary_field(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Summarize subtask",
            merge_strategy=MergeStrategy.SUMMARY,
        )
        result = _make_result(summary="Executive summary: all good")
        merged, merge_evt = await service.merge_session(parent, child, result)

        assert merged == "Executive summary: all good"
        assert merge_evt.merge_strategy == "summary"


# ---------------------------------------------------------------------------
# Multiple children from same parent
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMultipleChildren:
    async def test_fork_two_children_independently(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()

        child_a, evt_a = await service.fork_session(
            parent,
            user_id="user-2",
            title="Child A",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        child_b, evt_b = await service.fork_session(
            parent,
            user_id="user-3",
            title="Child B",
            merge_strategy=MergeStrategy.SUMMARY,
        )

        assert child_a.id != child_b.id
        assert child_a.fork_source_id == parent.id
        assert child_b.fork_source_id == parent.id
        assert evt_a.parent_conversation_id == parent.id
        assert evt_b.parent_conversation_id == parent.id

    async def test_merge_two_children_different_strategies(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_parent()

        child_a, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Child A",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        child_b, _ = await service.fork_session(
            parent,
            user_id="user-3",
            title="Child B",
            merge_strategy=MergeStrategy.SUMMARY,
        )

        result_a = _make_result(summary="Result A")
        result_b = _make_result(summary="Result B")

        merged_a, evt_a = await service.merge_session(parent, child_a, result_a)
        merged_b, evt_b = await service.merge_session(parent, child_b, result_b)

        assert "Result A" in merged_a
        assert evt_a.merge_strategy == "result_only"
        assert merged_b == "Result B"
        assert evt_b.merge_strategy == "summary"


# ---------------------------------------------------------------------------
# Nested fork (child of child)
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestNestedFork:
    async def test_fork_grandchild_from_child(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Child",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        grandchild, gc_evt = await service.fork_session(
            child,
            user_id="user-3",
            title="Grandchild",
            merge_strategy=MergeStrategy.SUMMARY,
        )

        assert grandchild.fork_source_id == child.id
        assert grandchild.parent_conversation_id == child.id
        assert gc_evt.parent_conversation_id == child.id
        assert gc_evt.child_conversation_id == grandchild.id

    async def test_merge_grandchild_then_child(self, service: SessionForkMergeService) -> None:
        parent = _make_parent()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Child",
            merge_strategy=MergeStrategy.FULL_HISTORY,
        )
        grandchild, _ = await service.fork_session(
            child,
            user_id="user-3",
            title="Grandchild",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )

        gc_result = _make_result(summary="GC done", name="gc-agent")
        gc_merged, _ = await service.merge_session(child, grandchild, gc_result)

        child_result = _make_result(summary="Child done")
        child_merged, evt = await service.merge_session(
            parent, child, child_result, child_messages=[gc_merged, "Extra step"]
        )

        assert "GC done" in child_merged
        assert "Extra step" in child_merged
        assert evt.merge_strategy == "full_history"


# ---------------------------------------------------------------------------
# Event data integrity
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestEventDataIntegrity:
    async def test_fork_event_serializes_to_dict(self, service: SessionForkMergeService) -> None:
        parent = _make_parent(conv_id="p-100")
        child, fork_evt = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        d = fork_evt.to_event_dict()
        assert d["type"] == "session_forked"
        assert d["data"]["parent_conversation_id"] == "p-100"
        assert d["data"]["child_conversation_id"] == child.id

    async def test_merge_event_serializes_to_dict(self, service: SessionForkMergeService) -> None:
        parent = _make_parent(conv_id="p-200")
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.SUMMARY,
        )
        result = _make_result(summary="ok")
        _, merge_evt = await service.merge_session(parent, child, result)
        d = merge_evt.to_event_dict()
        assert d["type"] == "session_merged"
        assert d["data"]["parent_conversation_id"] == "p-200"
        assert d["data"]["merge_strategy"] == "summary"
