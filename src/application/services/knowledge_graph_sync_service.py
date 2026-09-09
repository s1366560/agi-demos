"""Portable derived-record sync commands; wired through the same authority gate."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.domain.model.knowledge_sync.contracts import (
    GraphSyncMutation,
    GraphSyncResolution,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncScope,
    require_change_id,
    require_identifier,
)
from src.domain.ports.repositories.knowledge_graph_sync_repository import (
    KnowledgeGraphSyncRepository,
)


@dataclass(frozen=True, kw_only=True)
class KnowledgeGraphSyncService:
    repository: KnowledgeGraphSyncRepository

    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope:
        return await self.repository.resolve_scope(actor_id, project_id)

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: GraphSyncMutation
    ) -> KnowledgeSyncOutcome:
        require_change_id(change_id)
        return await self.repository.mutate_graph(scope, change_id, mutation)

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: GraphSyncResolution
    ) -> KnowledgeSyncOutcome:
        require_change_id(change_id)
        return await self.repository.resolve_graph(scope, change_id, resolution)

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
        return await self.repository.graph_changes(scope, after, limit)

    async def conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        require_change_id(conflict_id)
        return await self.repository.graph_conflict(scope, conflict_id)

    async def object(self, scope: KnowledgeSyncScope, object_id: str) -> dict[str, Any]:
        require_identifier(object_id)
        return await self.repository.graph_object(scope, object_id)


@dataclass(frozen=True, kw_only=True)
class KnowledgeGraphSyncApplication:
    """Injected by a generation-owned operation, never a global session fallback."""

    service: KnowledgeGraphSyncService
    commit: Callable[[], Awaitable[None]]
