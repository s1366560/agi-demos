"""Request-session repository boundary for derived graph record synchronization."""

from __future__ import annotations

from typing import Any, Protocol

from src.domain.model.knowledge_sync.contracts import (
    GraphSyncMutation,
    GraphSyncResolution,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncScope,
)


class KnowledgeGraphSyncRepository(Protocol):
    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope: ...

    async def mutate_graph(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: GraphSyncMutation
    ) -> KnowledgeSyncOutcome: ...

    async def resolve_graph(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: GraphSyncResolution
    ) -> KnowledgeSyncOutcome: ...

    async def graph_changes(
        self, scope: KnowledgeSyncScope, after: int, limit: int
    ) -> KnowledgeSyncPage: ...

    async def graph_conflict(
        self, scope: KnowledgeSyncScope, conflict_id: str
    ) -> dict[str, Any]: ...

    async def graph_object(self, scope: KnowledgeSyncScope, object_id: str) -> dict[str, Any]: ...
