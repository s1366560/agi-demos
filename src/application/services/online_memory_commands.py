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
from src.domain.ports.repositories.online_memory_repository import (
    OnlineMemoryContext,
    OnlineMemoryRepository,
)


class OnlineMemoryCommands:
    def __init__(self, repository: OnlineMemoryRepository) -> None:
        super().__init__()
        self.repository = repository

    async def open(self, actor_id: str, project_id: str) -> OnlineMemoryContext:
        return await self.repository.open(actor_id, project_id)

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
