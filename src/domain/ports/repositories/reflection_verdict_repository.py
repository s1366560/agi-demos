"""Port for persisting and querying ``ReflectionVerdict`` audit rows.

The reflection loop produces verdicts (CREATE / REINFORCE / DEPRECATE / NOOP)
on each sweep. We persist them so the UI can render the
"lessons learned" timeline and operators can audit the agent's reasoning.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from src.domain.model.flow.reflection_verdict import ReflectionVerdict


@dataclass(frozen=True)
class StoredReflectionVerdict:
    """A persisted verdict with its database identity and timestamp."""

    id: str
    project_id: str
    verdict: ReflectionVerdict
    created_at: datetime


class ReflectionVerdictRepository(ABC):
    """Read/write port for the ``reflection_verdicts`` table."""

    @abstractmethod
    async def record(
        self, *, project_id: str, verdict: ReflectionVerdict
    ) -> StoredReflectionVerdict:
        """Persist ``verdict`` for ``project_id``. Returns the stored row."""

    @abstractmethod
    async def list_for_project(
        self,
        project_id: str,
        *,
        limit: int = 100,
    ) -> list[StoredReflectionVerdict]:
        """Return the most-recent verdicts for ``project_id``."""


__all__ = [
    "ReflectionVerdictRepository",
    "StoredReflectionVerdict",
]
