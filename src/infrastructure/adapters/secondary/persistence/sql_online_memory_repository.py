"""Hold the bootstrap Project lock from enrollment decision through outer commit."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncScope,
    MemorySyncMutation,
)
from src.domain.ports.repositories.online_memory_repository import OnlineMemoryContext
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import Project
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)


class SqlOnlineMemoryRepository:
    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self.db = db

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
