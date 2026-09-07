"""Portable sync commands; authority wiring remains gated until all writers enroll."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncMutation,
    require_change_id,
)
from src.domain.ports.repositories.knowledge_sync_repository import KnowledgeSyncRepository


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncService:
    repository: KnowledgeSyncRepository

    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope:
        return await self.repository.resolve_scope(actor_id, project_id)

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome:
        require_change_id(change_id)
        return await self.repository.mutate(scope, change_id, mutation)

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: KnowledgeSyncResolution
    ) -> KnowledgeSyncOutcome:
        require_change_id(change_id)
        return await self.repository.resolve(scope, change_id, resolution)

    async def changes(
        self, scope: KnowledgeSyncScope, after: int = 0, limit: int = 100
    ) -> KnowledgeSyncPage:
        if (
            type(after) is not int
            or not 0 <= after <= 2**63 - 1
            or type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise KnowledgeSyncError("knowledge_sync_cursor_invalid")
        return await self.repository.changes(scope, after, limit)

    async def conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        require_change_id(conflict_id)
        return await self.repository.conflict(scope, conflict_id)


@dataclass(frozen=True, kw_only=True)
class KnowledgeSyncApplication:
    """Injected by a future generation-owned operation, never a global session fallback."""

    service: KnowledgeSyncService
    commit: Callable[[], Awaitable[None]]
