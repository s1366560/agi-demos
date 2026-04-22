"""Track B · multi-agent flow integration tests.

Composes the shipped modules end-to-end (without DB/Redis) to prove the
pieces wire together under the Agent First rule:

    ConversationAwareRouter → HITL policy + FIFO queue → Supervisor
    verdict → TerminationService three-gate → AgentConversationFinishedEvent

Each scenario exercises several layers simultaneously; unit tests still
cover each layer in isolation.

Agent First compliance note: these tests only construct synthetic inputs
(enum values, structured events, explicit mentions). They never assert on
message text parsing — that would be exactly the anti-pattern the rule
forbids.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.application.services.agent.termination_service import (
    TerminationContext,
    TerminationService,
)
from src.domain.events.agent_events import AgentConversationFinishedEvent
from src.domain.model.agent.conversation.conversation import (
    Conversation,
    ConversationStatus,
)
from src.domain.model.agent.conversation.conversation_mode import ConversationMode
from src.domain.model.agent.conversation.hitl_policy import (
    HitlCategory,
    HitlVisibility,
    resolve_hitl_policy,
)
from src.domain.model.agent.conversation.message import Message, MessageRole, MessageType
from src.domain.model.agent.conversation.pending_review import (
    PendingReview,
)
from src.domain.model.agent.conversation.termination import (
    BudgetCounters,
    TerminationReason,
)
from src.domain.model.agent.conversation.verdict_status import VerdictStatus
from src.domain.model.agent.routing_context import RoutingContext
from src.infrastructure.adapters.secondary.notifications.in_memory_receipt_notifier import (
    InMemoryReceiptNotifier,
)
from src.infrastructure.adapters.secondary.persistence.in_memory_hitl_queue import (
    InMemoryHitlQueue,
)
from src.infrastructure.agent.routing.conversation_aware_router import (
    ConversationAwareRouter,
)

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


@dataclass
class _CapturingEventSink:
    published: list[Any] = field(default_factory=list)

    async def publish(self, event: Any) -> None:
        self.published.append(event)


def _build_conversation(
    *,
    mode: ConversationMode,
    participants: list[str],
    coordinator: str | None = None,
    focused: str | None = None,
) -> Conversation:
    return Conversation(
        project_id="proj-1",
        tenant_id="tenant-1",
        user_id="user-1",
        title="multi-agent",
        status=ConversationStatus.ACTIVE,
        participant_agents=participants,
        conversation_mode=mode,
        coordinator_agent_id=coordinator,
        focused_agent_id=focused,
    )


def _message(mentions: list[str] | None = None) -> Message:
    return Message(
        conversation_id="conv-1",
        role=MessageRole.USER,
        content="payload-irrelevant-agent-first-rule",
        message_type=MessageType.TEXT,
        mentions=mentions or [],
    )


def _ctx() -> RoutingContext:
    return RoutingContext(conversation_id="conv-1", project_id="proj-1", tenant_id="tenant-1")


def _caps(
    *,
    max_turns: int | None = None,
    max_usd: float | None = None,
    max_wall_seconds: int | None = None,
) -> dict[str, int | float | None]:
    return {
        "max_turns": max_turns,
        "max_usd": max_usd,
        "max_wall_seconds": max_wall_seconds,
    }


# ---------------------------------------------------------------------------
# 1. Multi-agent routing with structured mentions — SHARED/ISOLATED/AUTONOMOUS
# ---------------------------------------------------------------------------


class TestRoutingComposition:
    """The router consults the conversation aggregate; inner binding fallback
    is only invoked when no structural rule selects a winner."""

    async def test_mention_overrides_mode(self) -> None:
        """Explicit @mention beats coordinator/focused across all modes."""
        for mode in (
            ConversationMode.MULTI_AGENT_SHARED,
            ConversationMode.MULTI_AGENT_ISOLATED,
            ConversationMode.AUTONOMOUS,
        ):
            conv = _build_conversation(
                mode=mode,
                participants=["a", "b", "coordinator"],
                coordinator="coordinator",
                focused="a",
            )
            repo = AsyncMock()
            repo.find_by_id.return_value = conv
            inner = AsyncMock()
            router = ConversationAwareRouter(inner=inner, conversation_repository=repo)

            winner = await router.resolve_agent(_message(mentions=["b"]), _ctx())
            assert winner == "b", f"mention should win in {mode}"
            inner.resolve_agent.assert_not_called()

    async def test_shared_mode_routes_to_coordinator(self) -> None:
        conv = _build_conversation(
            mode=ConversationMode.MULTI_AGENT_SHARED,
            participants=["a", "coordinator"],
            coordinator="coordinator",
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = conv
        inner = AsyncMock()
        router = ConversationAwareRouter(inner=inner, conversation_repository=repo)

        assert await router.resolve_agent(_message(), _ctx()) == "coordinator"
        inner.resolve_agent.assert_not_called()

    async def test_isolated_mode_prefers_focused(self) -> None:
        conv = _build_conversation(
            mode=ConversationMode.MULTI_AGENT_ISOLATED,
            participants=["a", "b", "coordinator"],
            coordinator="coordinator",
            focused="b",
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = conv
        inner = AsyncMock()
        router = ConversationAwareRouter(inner=inner, conversation_repository=repo)

        assert await router.resolve_agent(_message(), _ctx()) == "b"

    async def test_autonomous_requires_coordinator(self) -> None:
        """AUTONOMOUS without coordinator falls through to inner router
        rather than silently electing someone."""
        conv = _build_conversation(
            mode=ConversationMode.AUTONOMOUS,
            participants=["a", "b"],
            coordinator=None,
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = conv
        inner = AsyncMock()
        inner.resolve_agent.return_value = "fallback-binding"
        router = ConversationAwareRouter(inner=inner, conversation_repository=repo)

        assert await router.resolve_agent(_message(), _ctx()) == "fallback-binding"
        inner.resolve_agent.assert_awaited_once()

    async def test_unknown_mention_ignored_falls_back_to_mode(self) -> None:
        """Mention of non-participant is a no-op; mode-resolution continues."""
        conv = _build_conversation(
            mode=ConversationMode.MULTI_AGENT_SHARED,
            participants=["coordinator", "a"],
            coordinator="coordinator",
        )
        repo = AsyncMock()
        repo.find_by_id.return_value = conv
        inner = AsyncMock()
        router = ConversationAwareRouter(inner=inner, conversation_repository=repo)

        assert await router.resolve_agent(_message(mentions=["stranger"]), _ctx()) == "coordinator"


# ---------------------------------------------------------------------------
# 2. HITL three-tier: declared category + structural upgrade + FIFO queue
# ---------------------------------------------------------------------------


class TestHitlPolicyAndQueue:
    async def test_declared_category_propagates_when_no_intersection(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.INFORMATIONAL,
            mode=ConversationMode.MULTI_AGENT_SHARED,
            tool_side_effects=["write_file"],
            blocking_categories=["external_payment"],
        )
        assert decision.effective_category is HitlCategory.INFORMATIONAL
        assert not decision.structurally_upgraded
        assert decision.visibility is HitlVisibility.ROOM

    async def test_structural_upgrade_fires_on_intersection(self) -> None:
        decision = resolve_hitl_policy(
            declared_category=HitlCategory.PREFERENCE,
            mode=ConversationMode.AUTONOMOUS,
            tool_side_effects=["external_payment", "network"],
            blocking_categories=["external_payment", "filesystem_delete"],
        )
        assert decision.effective_category is HitlCategory.BLOCKING_HUMAN_ONLY
        assert decision.structurally_upgraded
        assert "external_payment" in decision.blocking_intersection
        assert decision.visibility is HitlVisibility.ROOM

    async def test_visibility_follows_mode(self) -> None:
        single = resolve_hitl_policy(
            declared_category=HitlCategory.INFORMATIONAL,
            mode=ConversationMode.SINGLE_AGENT,
            tool_side_effects=[],
            blocking_categories=[],
        )
        isolated = resolve_hitl_policy(
            declared_category=HitlCategory.INFORMATIONAL,
            mode=ConversationMode.MULTI_AGENT_ISOLATED,
            tool_side_effects=[],
            blocking_categories=[],
        )
        assert single.visibility is HitlVisibility.PRIVATE
        assert isolated.visibility is HitlVisibility.PRIVATE

    async def test_queue_serializes_fifo_and_dequeue(self) -> None:
        queue = InMemoryHitlQueue()
        reviews = [
            PendingReview(
                id=f"r{i}",
                conversation_id="conv-1",
                scope_agent_id=f"agent-{i}",
                effective_category="blocking_human_only",
                declared_category="blocking_human_only",
                visibility="room",
                question=f"q{i}",
                created_at=datetime.now(UTC),
            )
            for i in range(3)
        ]
        for r in reviews:
            await queue.enqueue(r)

        assert await queue.size("conv-1") == 3
        first = await queue.peek("conv-1")
        assert first is not None and first.id == "r0"

        await queue.dequeue("conv-1", "r0")
        assert (await queue.peek("conv-1")).id == "r1"  # type: ignore[union-attr]
        assert await queue.size("conv-1") == 2

        open_reviews = await queue.list_open("conv-1")
        assert [r.id for r in open_reviews] == ["r1", "r2"]


# ---------------------------------------------------------------------------
# 3. Three-gate termination end-to-end
# ---------------------------------------------------------------------------


class TestTerminationEndToEnd:
    """Each gate fires independently; finalize() emits event + receipt."""

    async def _svc(self) -> tuple[TerminationService, _CapturingEventSink, InMemoryReceiptNotifier]:
        sink = _CapturingEventSink()
        notifier = InMemoryReceiptNotifier()
        return (
            TerminationService(event_sink=sink, receipt_notifier=notifier),
            sink,
            notifier,
        )

    async def test_goal_gate_fires_when_coordinator_declares_done(self) -> None:
        svc, sink, notifier = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=100),
            counters=BudgetCounters(turns=5),
            goal_completed_event_id="evt-goal-1",
        )
        decision = svc.evaluate(ctx)
        assert decision is not None and decision.reason is TerminationReason.GOAL_COMPLETED

        await svc.finalize(ctx, decision)
        assert len(sink.published) == 1
        published = sink.published[0]
        assert isinstance(published, AgentConversationFinishedEvent)
        assert published.reason == TerminationReason.GOAL_COMPLETED.value
        assert len(notifier.delivered) == 1

    async def test_budget_gate_fires_on_turns_cap(self) -> None:
        svc, sink, _ = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=3, max_usd=999, max_wall_seconds=9999),
            counters=BudgetCounters(turns=3, usd=0.01, wall_seconds=1),
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.BUDGET_TURNS

        await svc.finalize(ctx, decision)
        assert sink.published[0].reason == TerminationReason.BUDGET_TURNS.value

    async def test_safety_gate_fires_on_looping_verdict(self) -> None:
        svc, sink, _ = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=100),
            counters=BudgetCounters(turns=10),
            latest_verdict=VerdictStatus.LOOPING,
            latest_verdict_rationale="supervisor judgment",
        )
        decision = svc.evaluate(ctx)
        assert decision is not None and decision.reason is TerminationReason.SAFETY_LOOPING

        await svc.finalize(ctx, decision)
        assert sink.published[0].reason == TerminationReason.SAFETY_LOOPING.value

    async def test_doom_loop_flag_alone_does_not_terminate(self) -> None:
        """Agent First: structural doom-loop signal without a supervisor
        LOOPING verdict must NOT terminate the conversation."""
        svc, _, _ = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=100),
            counters=BudgetCounters(turns=10),
            doom_loop_triggered=True,
        )
        assert svc.evaluate(ctx) is None

    async def test_doom_loop_with_looping_verdict_upgrades_reason(self) -> None:
        svc, sink, _ = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=100),
            counters=BudgetCounters(turns=10),
            latest_verdict=VerdictStatus.LOOPING,
            doom_loop_triggered=True,
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.SAFETY_DOOM_LOOP

        await svc.finalize(ctx, decision)
        assert sink.published[0].reason == TerminationReason.SAFETY_DOOM_LOOP.value

    async def test_goal_wins_when_budget_also_breached(self) -> None:
        """Goal gate has priority — coordinator's declared success wins
        over coincidental budget breach in the same tick."""
        svc, _, _ = await self._svc()
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            **_caps(max_turns=3),
            counters=BudgetCounters(turns=3),
            goal_completed_event_id="evt-goal",
            latest_verdict=VerdictStatus.LOOPING,
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        assert decision.reason is TerminationReason.GOAL_COMPLETED

    async def test_notifier_failure_does_not_block_event(self) -> None:
        sink = _CapturingEventSink()

        class _Broken(InMemoryReceiptNotifier):
            async def deliver(self, **kwargs: Any) -> bool:  # type: ignore[override]
                raise RuntimeError("downstream offline")

        svc = TerminationService(event_sink=sink, receipt_notifier=_Broken())
        ctx = TerminationContext(
            conversation_id="c1",
            user_id="u1",
            counters=BudgetCounters(turns=1),
            goal_completed_event_id="e",
        )
        decision = svc.evaluate(ctx)
        assert decision is not None
        await svc.finalize(ctx, decision)
        assert len(sink.published) == 1
