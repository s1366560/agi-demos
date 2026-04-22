"""HITL queue port (Track B P2-3 phase-2).

FIFO queue for human-in-the-loop requests. Per-conversation serial
ordering is a structural protocol guarantee (only one HITL prompt at
a time to the operator) — not an agent judgment call.

The port intentionally keeps the API minimal; a Redis-ZSET-backed
implementation or an in-memory one both satisfy the contract.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.agent.conversation.pending_review import PendingReview

__all__ = ["HitlQueuePort"]


class HitlQueuePort(ABC):
    """Per-conversation FIFO queue for HITL pending reviews."""

    @abstractmethod
    async def enqueue(self, review: PendingReview) -> None:
        """Append a review to the tail of its conversation's queue."""

    @abstractmethod
    async def peek(self, conversation_id: str) -> PendingReview | None:
        """Return the oldest still-open review in the conversation, or None."""

    @abstractmethod
    async def dequeue(self, conversation_id: str, review_id: str) -> bool:
        """Remove a specific review; return True if it was present."""

    @abstractmethod
    async def size(self, conversation_id: str) -> int:
        """Number of open reviews in the conversation's queue."""

    @abstractmethod
    async def list_open(self, conversation_id: str) -> list[PendingReview]:
        """All open reviews in FIFO order (head first)."""
