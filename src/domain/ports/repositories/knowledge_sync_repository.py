"""Request-session repository boundary for durable memory synchronization."""

from __future__ import annotations

from typing import Any, Protocol

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncMutation,
)


class KnowledgeSyncRepository(Protocol):
    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope: ...

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome: ...

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: KnowledgeSyncResolution
    ) -> KnowledgeSyncOutcome: ...

    async def changes(
        self, scope: KnowledgeSyncScope, after: int, limit: int
    ) -> KnowledgeSyncPage: ...

    async def conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]: ...
