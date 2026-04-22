"""In-memory HITL queue (Track B P2-3 phase-2).

Per-conversation FIFO. Async-safe via a per-conversation ``asyncio.Lock``.

Suitable for unit tests and single-process deployments. Redis-backed
implementations can slot in by implementing the same
:class:`HitlQueuePort` interface without touching callers.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import override

from src.domain.model.agent.conversation.pending_review import (
    PendingReview,
    PendingReviewStatus,
)
from src.domain.ports.agent.hitl_queue_port import HitlQueuePort

__all__ = ["InMemoryHitlQueue"]


class InMemoryHitlQueue(HitlQueuePort):
    """Thread-safe (asyncio) FIFO queue keyed by conversation id.

    Open reviews are kept in insertion order. Non-open reviews
    (resolved / withdrawn / cancelled) are removed on next access.
    """

    def __init__(self) -> None:
        self._queues: dict[str, list[PendingReview]] = defaultdict(list)
        self._locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    def _lock_for(self, conversation_id: str) -> asyncio.Lock:
        return self._locks[conversation_id]

    @override
    async def enqueue(self, review: PendingReview) -> None:
        async with self._lock_for(review.conversation_id):
            self._queues[review.conversation_id].append(review)

    @override
    async def peek(self, conversation_id: str) -> PendingReview | None:
        async with self._lock_for(conversation_id):
            queue = self._queues.get(conversation_id, [])
            for item in queue:
                if item.status is PendingReviewStatus.OPEN:
                    return item
            return None

    @override
    async def dequeue(self, conversation_id: str, review_id: str) -> bool:
        async with self._lock_for(conversation_id):
            queue = self._queues.get(conversation_id, [])
            for idx, item in enumerate(queue):
                if item.id == review_id:
                    del queue[idx]
                    return True
            return False

    @override
    async def size(self, conversation_id: str) -> int:
        async with self._lock_for(conversation_id):
            return sum(
                1
                for item in self._queues.get(conversation_id, [])
                if item.status is PendingReviewStatus.OPEN
            )

    @override
    async def list_open(self, conversation_id: str) -> list[PendingReview]:
        async with self._lock_for(conversation_id):
            return [
                item
                for item in self._queues.get(conversation_id, [])
                if item.status is PendingReviewStatus.OPEN
            ]
