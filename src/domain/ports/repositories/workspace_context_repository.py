"""Repository contract for authoritative desktop workspace context."""

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextCandidate,
    WorkspaceContextSnapshot,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)


class WorkspaceContextRepository(ABC):
    @abstractmethod
    async def get_accessible(self, user_id: str) -> WorkspaceContextAccess | None:
        """Return the current context only when it remains accessible."""

    @abstractmethod
    async def get_current(self, user_id: str) -> WorkspaceContextSnapshot | None:
        """Return the persisted context as continuity evidence, accessible or not."""

    @abstractmethod
    async def list_candidates(self, user_id: str) -> tuple[WorkspaceContextCandidate, ...]:
        """Enumerate every structurally accessible scope without selecting one."""

    @abstractmethod
    async def initialize(
        self,
        user_id: str,
        *,
        candidate: WorkspaceContextCandidate,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        """Persist one explicitly selected accessible candidate under a revision fence."""

    @abstractmethod
    async def switch(
        self,
        user_id: str,
        *,
        actor_api_key_id: str | None,
        request: WorkspaceContextSwitchRequest,
        observed_at: datetime,
    ) -> WorkspaceContextSwitchOutcome:
        """Revision-fenced, idempotent switch to an accessible tenant/project scope."""
