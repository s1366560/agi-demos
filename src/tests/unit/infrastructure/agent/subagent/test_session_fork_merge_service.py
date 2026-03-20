"""Tests for SessionForkMergeService -- Phase 3 Wave 6.

Verifies fork/merge lifecycle: fork creates linked child conversations,
merge applies the correct strategy (RESULT_ONLY, FULL_HISTORY, SUMMARY).
"""

from __future__ import annotations

import pytest

from src.domain.events.agent_events import SessionForkedEvent, SessionMergedEvent
from src.domain.model.agent.conversation.conversation import Conversation, ConversationStatus
from src.domain.model.agent.merge_strategy import MergeStrategy
from src.domain.model.agent.subagent_result import SubAgentResult
from src.domain.ports.agent.session_fork_merge_port import SessionForkMergePort
from src.infrastructure.agent.subagent.session_fork_merge_service import (
    SessionForkMergeService,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_conversation(
    *,
    conv_id: str = "conv-parent",
    project_id: str = "proj-1",
    tenant_id: str = "t-1",
    user_id: str = "user-1",
    title: str = "Parent conversation",
    merge_strategy: MergeStrategy = MergeStrategy.RESULT_ONLY,
    fork_source_id: str | None = None,
    parent_conversation_id: str | None = None,
    fork_context_snapshot: str | None = None,
) -> Conversation:
    return Conversation(
        id=conv_id,
        project_id=project_id,
        tenant_id=tenant_id,
        user_id=user_id,
        title=title,
        merge_strategy=merge_strategy,
        fork_source_id=fork_source_id,
        parent_conversation_id=parent_conversation_id,
        fork_context_snapshot=fork_context_snapshot,
    )


def _make_result(
    *,
    success: bool = True,
    summary: str = "Task completed",
    name: str = "research-agent",
    tool_calls: int = 3,
    tokens: int = 500,
) -> SubAgentResult:
    return SubAgentResult(
        subagent_id="sa-1",
        subagent_name=name,
        summary=summary,
        success=success,
        tool_calls_count=tool_calls,
        tokens_used=tokens,
    )


@pytest.fixture()
def service() -> SessionForkMergeService:
    return SessionForkMergeService()


# ---------------------------------------------------------------------------
# Protocol compliance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestProtocolCompliance:
    def test_service_satisfies_protocol(self, service: SessionForkMergeService) -> None:
        assert isinstance(service, SessionForkMergePort)


# ---------------------------------------------------------------------------
# fork_session
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestForkSession:
    async def test_fork_creates_child_conversation(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="user-2",
            title="Child task",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert child.fork_source_id == parent.id
        assert child.parent_conversation_id == parent.id
        assert child.user_id == "user-2"
        assert child.title == "Child task"

    async def test_fork_preserves_project_and_tenant(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation(project_id="p-99", tenant_id="t-99")
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.SUMMARY,
        )
        assert child.project_id == "p-99"
        assert child.tenant_id == "t-99"

    async def test_fork_stores_merge_strategy(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.FULL_HISTORY,
        )
        assert child.merge_strategy is MergeStrategy.FULL_HISTORY

    async def test_fork_stores_context_snapshot(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            context_snapshot='{"messages": []}',
        )
        assert child.fork_context_snapshot == '{"messages": []}'

    async def test_fork_without_context_snapshot(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert child.fork_context_snapshot is None

    async def test_fork_emits_session_forked_event(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation(conv_id="parent-id")
        child, event = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert isinstance(event, SessionForkedEvent)
        assert event.parent_conversation_id == "parent-id"
        assert event.child_conversation_id == child.id

    async def test_fork_child_has_active_status(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert child.status is ConversationStatus.ACTIVE

    async def test_fork_child_has_unique_id(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert child.id != parent.id

    async def test_fork_child_is_forked_property(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child, _ = await service.fork_session(
            parent,
            user_id="u-1",
            title="Sub",
            merge_strategy=MergeStrategy.RESULT_ONLY,
        )
        assert child.is_forked is True
        assert parent.is_forked is False


# ---------------------------------------------------------------------------
# merge_session -- RESULT_ONLY strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeResultOnly:
    async def test_merge_result_only_uses_to_context_message(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            fork_source_id=parent.id,
            parent_conversation_id=parent.id,
        )
        result = _make_result(summary="Found 3 papers")
        merged, _ = await service.merge_session(parent, child, result)
        assert merged == result.to_context_message()

    async def test_merge_result_only_success(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            fork_source_id=parent.id,
        )
        result = _make_result(success=True, summary="Done", name="analyst")
        merged, _ = await service.merge_session(parent, child, result)
        assert "completed successfully" in merged
        assert "Done" in merged

    async def test_merge_result_only_failure(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            fork_source_id=parent.id,
        )
        result_obj = SubAgentResult(
            subagent_id="sa-1",
            subagent_name="builder",
            summary="Partial",
            success=False,
            error="Timeout exceeded",
        )
        merged, _ = await service.merge_session(parent, child, result_obj)
        assert "failed" in merged
        assert "Timeout exceeded" in merged


# ---------------------------------------------------------------------------
# merge_session -- FULL_HISTORY strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeFullHistory:
    async def test_merge_full_history_joins_messages(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.FULL_HISTORY,
            fork_source_id=parent.id,
            title="Research task",
        )
        result = _make_result()
        messages = ["User: find papers", "Assistant: I found 3 papers"]
        merged, _ = await service.merge_session(parent, child, result, child_messages=messages)
        assert "Research task" in merged
        assert "find papers" in merged
        assert "I found 3 papers" in merged

    async def test_merge_full_history_empty_messages(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.FULL_HISTORY,
            fork_source_id=parent.id,
            title="Empty task",
        )
        result = _make_result()
        merged, _ = await service.merge_session(parent, child, result)
        assert "Empty task" in merged
        assert "No messages recorded" in merged

    async def test_merge_full_history_none_messages(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.FULL_HISTORY,
            fork_source_id=parent.id,
        )
        result = _make_result()
        merged, _ = await service.merge_session(parent, child, result, child_messages=None)
        assert "No messages recorded" in merged

    async def test_merge_full_history_single_message(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.FULL_HISTORY,
            fork_source_id=parent.id,
        )
        result = _make_result()
        merged, _ = await service.merge_session(
            parent, child, result, child_messages=["Only one message"]
        )
        assert "Only one message" in merged
        assert "---" not in merged


# ---------------------------------------------------------------------------
# merge_session -- SUMMARY strategy
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeSummary:
    async def test_merge_summary_uses_result_summary(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.SUMMARY,
            fork_source_id=parent.id,
        )
        result = _make_result(summary="Found 3 relevant papers on RAG techniques")
        merged, _ = await service.merge_session(parent, child, result)
        assert merged == "Found 3 relevant papers on RAG techniques"

    async def test_merge_summary_empty_summary(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="child-1",
            merge_strategy=MergeStrategy.SUMMARY,
            fork_source_id=parent.id,
        )
        result = _make_result(summary="")
        merged, _ = await service.merge_session(parent, child, result)
        assert merged == ""


# ---------------------------------------------------------------------------
# merge_session -- event emission
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeEventEmission:
    async def test_merge_emits_session_merged_event(self, service: SessionForkMergeService) -> None:
        parent = _make_conversation(conv_id="p-1")
        child = _make_conversation(
            conv_id="c-1",
            merge_strategy=MergeStrategy.RESULT_ONLY,
            fork_source_id="p-1",
        )
        result = _make_result()
        _, event = await service.merge_session(parent, child, result)
        assert isinstance(event, SessionMergedEvent)
        assert event.parent_conversation_id == "p-1"
        assert event.child_conversation_id == "c-1"
        assert event.merge_strategy == "result_only"

    async def test_merge_event_contains_strategy_value(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="c-1",
            merge_strategy=MergeStrategy.FULL_HISTORY,
            fork_source_id=parent.id,
        )
        result = _make_result()
        _, event = await service.merge_session(parent, child, result, child_messages=["msg"])
        assert event.merge_strategy == "full_history"


# ---------------------------------------------------------------------------
# merge_session -- fallback when merge_strategy is None
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestMergeFallback:
    async def test_merge_none_strategy_defaults_to_result_only(
        self, service: SessionForkMergeService
    ) -> None:
        parent = _make_conversation()
        child = _make_conversation(
            conv_id="c-1",
            fork_source_id=parent.id,
        )
        object.__setattr__(child, "merge_strategy", None)
        result = _make_result()
        merged, event = await service.merge_session(parent, child, result)
        assert merged == result.to_context_message()
        assert event.merge_strategy == "result_only"
