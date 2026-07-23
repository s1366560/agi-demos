"""Repository contract for authoritative desktop workspace context."""

from abc import ABC, abstractmethod
from datetime import datetime

from src.domain.model.auth.workspace_context import (
    WorkspaceContextAccess,
    WorkspaceContextSwitchOutcome,
    WorkspaceContextSwitchRequest,
)


class WorkspaceContextRepository(ABC):
    @abstractmethod
    async def get_or_initialize(
        self,
        user_id: str,
        observed_at: datetime,
    ) -> WorkspaceContextAccess:
        """Load the current accessible context or initialize its deterministic default."""

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
