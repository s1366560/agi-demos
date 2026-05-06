"""Playbook Repository port — CRUD for reflection-distilled playbooks.

Implementations should preserve the agent-authored ``rationale`` audit trail
when applying ``ReflectionVerdict`` updates.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.domain.model.flow.playbook import Playbook, PlaybookStatus


class PlaybookRepository(ABC):
    """Persistence interface for ``Playbook`` aggregates."""

    @abstractmethod
    async def save(self, playbook: Playbook) -> Playbook:
        """Insert or update a playbook (upsert by ``id``)."""

    @abstractmethod
    async def find_by_id(self, playbook_id: str) -> Playbook | None: ...

    @abstractmethod
    async def find_by_project(
        self,
        project_id: str,
        *,
        status: PlaybookStatus | None = None,
        limit: int = 100,
    ) -> list[Playbook]: ...

    @abstractmethod
    async def record_hit(self, playbook_id: str) -> None:
        """Increment hit count + bump ``last_used_at``. No-op if missing."""
