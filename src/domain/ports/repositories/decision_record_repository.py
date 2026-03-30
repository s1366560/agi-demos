from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.trust.decision_record import DecisionRecord


class DecisionRecordRepository(ABC):
    """Repository interface for decision record persistence."""

    @abstractmethod
    async def save(self, record: DecisionRecord) -> DecisionRecord: ...

    @abstractmethod
    async def find_by_id(self, record_id: str) -> DecisionRecord | None: ...

    @abstractmethod
    async def find_by_workspace(
        self,
        workspace_id: str,
        *,
        agent_id: str | None = None,
        decision_type: str | None = None,
    ) -> list[DecisionRecord]: ...

    @abstractmethod
    async def update(self, record: DecisionRecord) -> None: ...
