"""Transaction-owned online memory command and enrollment boundary."""

from dataclasses import dataclass
from typing import Literal, Protocol

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


@dataclass(frozen=True, kw_only=True)
class OnlineMemoryObjectActions:
    memory_id: str
    revision: int
    allowed_actions: tuple[Literal["update", "delete"], ...]


@dataclass(frozen=True, kw_only=True)
class OnlineMemoryCapabilities:
    tenant_id: str
    project_id: str
    actor_id: str
    allowed_actions: tuple[Literal["create"], ...]
    objects: tuple[OnlineMemoryObjectActions, ...]
    protocol_version: Literal[1] = 1


class OnlineMemoryRepository(Protocol):
    async def capabilities(
        self, actor_id: str, project_id: str, objects: tuple[tuple[str, int], ...]
    ) -> OnlineMemoryCapabilities | None: ...

    async def open(self, actor_id: str, project_id: str) -> OnlineMemoryContext: ...

    async def open_memory(self, actor_id: str, memory_id: str) -> OnlineMemoryContext | None: ...

    async def patch(
        self, scope: KnowledgeSyncScope, change_id: str, patch: MemoryOnlinePatch
    ) -> KnowledgeSyncOutcome: ...

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome: ...
