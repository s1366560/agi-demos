"""Transaction-owned online memory command and enrollment boundary."""

from dataclasses import dataclass
from typing import Protocol

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncOutcome,
    KnowledgeSyncScope,
    MemorySyncMutation,
)
from src.domain.model.knowledge_sync.online_patch import MemoryOnlinePatch


@dataclass(frozen=True, kw_only=True)
class OnlineMemoryContext:
    scope: KnowledgeSyncScope
    enabled: bool


class OnlineMemoryRepository(Protocol):
    async def open(self, actor_id: str, project_id: str) -> OnlineMemoryContext: ...

    async def open_memory(self, actor_id: str, memory_id: str) -> OnlineMemoryContext | None: ...

    async def patch(
        self, scope: KnowledgeSyncScope, change_id: str, patch: MemoryOnlinePatch
    ) -> KnowledgeSyncOutcome: ...

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome: ...
