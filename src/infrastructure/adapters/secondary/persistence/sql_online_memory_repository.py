"""Hold the bootstrap Project lock from enrollment decision through outer commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncScope,
    MemorySyncMutation,
)
from src.domain.model.knowledge_sync.online_patch import MemoryOnlinePatch
from src.domain.ports.repositories.online_memory_repository import (
    OnlineMemoryCapabilities,
    OnlineMemoryContext,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project
from src.infrastructure.adapters.secondary.persistence.online_memory_capabilities import (
    read_online_memory_capabilities,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)


class SqlOnlineMemoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self.db = db

    async def capabilities(
        self, actor_id: str, project_id: str, objects: tuple[tuple[str, int], ...]
    ) -> OnlineMemoryCapabilities | None:
        return await read_online_memory_capabilities(self.db, actor_id, project_id, objects)

    async def open(self, actor_id: str, project_id: str) -> OnlineMemoryContext:
        # Authorization is deliberately left to each path: legacy policy is
        # preserved when disabled, while mutate_online rechecks strict membership.
        project = await self.db.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if project is None:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        enrollment = await self.db.scalar(
            select(Enrollment)
            .where(Enrollment.project_id == project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if enrollment is None and self.db.get_bind().dialect.name == "postgresql":
            raise KnowledgeSyncError("knowledge_sync_fence_missing")
        if enrollment is not None and enrollment.tenant_id != project.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        return OnlineMemoryContext(
            scope=KnowledgeSyncScope(
                actor_id=actor_id, project_id=project.id, tenant_id=project.tenant_id
            ),
            enabled=enrollment.enabled if enrollment is not None else False,
        )

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome:
        return await SqlKnowledgeSyncRepository(self.db).mutate_online(scope, change_id, mutation)

    async def _memory_project(self, memory_id: str) -> str | None:
        project_id = await self.db.scalar(select(Memory.project_id).where(Memory.id == memory_id))
        if project_id is None:
            project_id = await self.db.scalar(
                select(Tombstone.project_id).where(Tombstone.memory_id == memory_id)
            )
        return project_id

    async def open_memory(self, actor_id: str, memory_id: str) -> OnlineMemoryContext | None:
        # Discover identity without retaining an ORM snapshot across the lock.
        project_id = await self._memory_project(memory_id)
        if project_id is None:
            return None
        context = await self.open(actor_id, project_id)
        current_project = await self._memory_project(memory_id)
        if current_project is not None and current_project != project_id:
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        return context

    async def patch(
        self, scope: KnowledgeSyncScope, change_id: str, patch: MemoryOnlinePatch
    ) -> KnowledgeSyncOutcome:
        return await SqlKnowledgeSyncRepository(self.db).mutate_online_patch(
            scope, change_id, patch
        )
