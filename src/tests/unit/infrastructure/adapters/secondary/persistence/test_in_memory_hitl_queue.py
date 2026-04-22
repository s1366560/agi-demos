"""Tests for ``InMemoryHitlQueue`` FIFO semantics."""

from __future__ import annotations

import pytest

from src.domain.model.agent.conversation.pending_review import (
    PendingReview,
    PendingReviewStatus,
)
from src.infrastructure.adapters.secondary.persistence.in_memory_hitl_queue import (
    InMemoryHitlQueue,
)


def _mk(pid: str, conv: str = "c1") -> PendingReview:
    return PendingReview(
        id=pid,
        conversation_id=conv,
        scope_agent_id="a1",
        effective_category="blocking_human_only",
        declared_category="blocking_human_only",
        visibility="private",
        question=f"Q{pid}",
    )


@pytest.mark.asyncio
async def test_enqueue_peek_fifo() -> None:
    q = InMemoryHitlQueue()
    await q.enqueue(_mk("r1"))
    await q.enqueue(_mk("r2"))
    await q.enqueue(_mk("r3"))

    head = await q.peek("c1")
    assert head is not None
    assert head.id == "r1"
    assert await q.size("c1") == 3


@pytest.mark.asyncio
async def test_dequeue_removes_specific_item() -> None:
    q = InMemoryHitlQueue()
    await q.enqueue(_mk("r1"))
    await q.enqueue(_mk("r2"))
    assert await q.dequeue("c1", "r1") is True
    assert await q.dequeue("c1", "r1") is False
    head = await q.peek("c1")
    assert head is not None and head.id == "r2"


@pytest.mark.asyncio
async def test_non_open_items_are_skipped_by_peek_and_size() -> None:
    q = InMemoryHitlQueue()
    r1 = _mk("r1")
    r1.status = PendingReviewStatus.RESOLVED
    r2 = _mk("r2")
    await q.enqueue(r1)
    await q.enqueue(r2)
    head = await q.peek("c1")
    assert head is not None and head.id == "r2"
    assert await q.size("c1") == 1


@pytest.mark.asyncio
async def test_queues_are_isolated_per_conversation() -> None:
    q = InMemoryHitlQueue()
    await q.enqueue(_mk("r1", conv="c1"))
    await q.enqueue(_mk("r1", conv="c2"))
    assert await q.size("c1") == 1
    assert await q.size("c2") == 1
    open_c1 = await q.list_open("c1")
    assert [r.conversation_id for r in open_c1] == ["c1"]


@pytest.mark.asyncio
async def test_empty_queue_returns_none() -> None:
    q = InMemoryHitlQueue()
    assert await q.peek("missing") is None
    assert await q.size("missing") == 0
    assert await q.list_open("missing") == []
