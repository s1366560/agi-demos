"""Repository port for ``DecisionLogEntry`` (Track B P2-3 phase-2)."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.agent.conversation.decision_log import DecisionLogEntry

__all__ = ["DecisionLogRepository"]


class DecisionLogRepository(ABC):
    """Persistence interface for judgmental-tool-call audit rows."""

    @abstractmethod
    async def append(self, entry: DecisionLogEntry) -> DecisionLogEntry:
        """Persist and return the entry (id assigned if empty)."""

    @abstractmethod
    async def list_for_conversation(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DecisionLogEntry]:
        """Oldest-first paginated list for a conversation."""

    @abstractmethod
    async def count(self, conversation_id: str) -> int:
        """Row count for a conversation."""
