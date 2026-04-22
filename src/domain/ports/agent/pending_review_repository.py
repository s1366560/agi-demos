"""Repository port for ``PendingReview`` (Track B P2-3 phase-2)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from src.domain.model.agent.conversation.pending_review import (
    PendingReview,
    PendingReviewStatus,
)

__all__ = ["PendingReviewRepository"]


class PendingReviewRepository(ABC):
    """Persistence interface for blocking-HITL pending reviews."""

    @abstractmethod
    async def create(self, review: PendingReview) -> PendingReview:
        """Persist and return the review (id assigned if empty)."""

    @abstractmethod
    async def get(self, review_id: str) -> PendingReview | None:
        """Load by id."""

    @abstractmethod
    async def list_open(self, conversation_id: str) -> list[PendingReview]:
        """All ``OPEN`` reviews for a conversation, oldest first."""

    @abstractmethod
    async def update_status(
        self,
        review_id: str,
        status: PendingReviewStatus,
        resolution_payload: dict[str, Any] | None = None,
    ) -> PendingReview | None:
        """Transition status; set ``resolved_at`` on terminal states."""
