"""Explicit online commands; callers retain transaction commit ownership."""

import json
from uuid import NAMESPACE_URL, uuid5

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    MemorySyncContent,
    MemorySyncMutation,
    require_change_id,
)
from src.domain.model.knowledge_sync.online_patch import MemoryOnlinePatch
from src.domain.ports.repositories.online_memory_repository import (
    OnlineMemoryCapabilities,
    OnlineMemoryContext,
    OnlineMemoryRepository,
)


class OnlineMemoryCommands:
    def __init__(self, repository: OnlineMemoryRepository) -> None:
        super().__init__()
        self.repository = repository

    async def capabilities(
        self, actor_id: str, project_id: str, objects: tuple[tuple[str, int], ...]
    ) -> OnlineMemoryCapabilities | None:
        return await self.repository.capabilities(actor_id, project_id, objects)

    async def open(self, actor_id: str, project_id: str) -> OnlineMemoryContext:
        return await self.repository.open(actor_id, project_id)

    async def open_memory(self, actor_id: str, memory_id: str) -> OnlineMemoryContext | None:
        return await self.repository.open_memory(actor_id, memory_id)

    async def patch(
        self, context: OnlineMemoryContext, change_id: str, patch: MemoryOnlinePatch
    ) -> KnowledgeSyncOutcome:
        if not context.enabled:
            raise KnowledgeSyncError("knowledge_sync_not_enrolled")
        require_change_id(change_id)
        return await self.repository.patch(context.scope, change_id, patch)

    async def delete(
        self,
        context: OnlineMemoryContext,
        change_id: str,
        memory_id: str,
        expected_revision: int,
    ) -> KnowledgeSyncOutcome:
        if not context.enabled:
            raise KnowledgeSyncError("knowledge_sync_not_enrolled")
        require_change_id(change_id)
        return await self.repository.mutate(
            context.scope,
            change_id,
            MemorySyncMutation(
                operation="delete", memory_id=memory_id, expected_revision=expected_revision
            ),
        )

    async def create(
        self,
        context: OnlineMemoryContext,
        change_id: str,
        expected_revision: int,
        content: MemorySyncContent,
    ) -> KnowledgeSyncOutcome:
        if not context.enabled:
            raise KnowledgeSyncError("knowledge_sync_not_enrolled")
        require_change_id(change_id)
        scope = context.scope
        # A stable resource identity follows the explicit client key. The server
        # never generates a replacement key for a client that omitted one.
        identity = json.dumps([scope.tenant_id, scope.project_id, scope.actor_id, change_id])
        return await self.repository.mutate(
            scope,
            change_id,
            MemorySyncMutation(
                operation="create",
                memory_id=str(uuid5(NAMESPACE_URL, "memstack:online-memory:" + identity)),
                expected_revision=expected_revision,
                content=content,
            ),
        )
