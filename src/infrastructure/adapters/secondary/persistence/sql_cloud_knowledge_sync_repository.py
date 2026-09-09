"""Enrollment-fenced production adapter over the durable sync foundation.

The project/enrollment locks remain held until the caller commits or rolls back.
The injected lifetime check belongs to the operation that created this adapter.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    GraphSyncMutation,
    GraphSyncResolution,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncMutation,
)
from src.domain.ports.repositories.knowledge_sync_enrollment_repository import (
    KnowledgeSyncEnrollmentState,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_access import (
    authorize_scope,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_graph_sync_repository import (
    SqlKnowledgeGraphSyncRepository,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_enrollment import (
    SqlKnowledgeSyncEnrollment,
)
from src.infrastructure.adapters.secondary.persistence.sql_knowledge_sync_repository import (
    SqlKnowledgeSyncRepository,
)


class SqlCloudKnowledgeSyncRepository:
    def __init__(
        self,
        db: AsyncSession,
        scope: KnowledgeSyncScope,
        current: Callable[[], None],
    ) -> None:
        super().__init__()
        self.db = db
        self.scope = scope
        self.current = current
        self.foundation = SqlKnowledgeSyncRepository(db)
        self.graph_foundation = SqlKnowledgeGraphSyncRepository(db)

    async def status(self) -> KnowledgeSyncEnrollmentState:
        self.current()
        project, member = await authorize_scope(
            self.db, self.scope.actor_id, self.scope.project_id, lock=True
        )
        self.current()
        if project.tenant_id != self.scope.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        # Bootstrap also holds the Project lock. An enrollment row lock here
        # would invert the legal derived-writer order: Memory -> enrollment.
        enrollment = await self.db.scalar(
            select(Enrollment)
            .where(Enrollment.project_id == self.scope.project_id)
            .execution_options(populate_existing=True)
        )
        self.current()
        if enrollment is None and self.db.get_bind().dialect.name == "postgresql":
            raise KnowledgeSyncError("knowledge_sync_fence_missing")
        if enrollment is not None and enrollment.tenant_id != self.scope.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        return KnowledgeSyncEnrollmentState(
            scope=self.scope,
            enabled=enrollment.enabled if enrollment else False,
            can_enroll=member.role in {"owner", "admin"},
            bootstrap_count=enrollment.bootstrap_count if enrollment else 0,
            next_cursor=enrollment.bootstrap_cursor if enrollment else 0,
        )

    async def bootstrap(self) -> KnowledgeSyncEnrollmentState:
        before = await self.status()
        if not before.can_enroll:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        _ = await SqlKnowledgeSyncEnrollment(self.db).bootstrap(self.scope)
        self.current()
        return replace(await self.status(), replayed=before.enabled)

    async def _admit(self, scope: KnowledgeSyncScope) -> None:
        self.current()
        if scope != self.scope:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        if not (await self.status()).enabled:
            raise KnowledgeSyncError("knowledge_sync_not_enrolled")
        self.current()

    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope:
        if actor_id != self.scope.actor_id or project_id != self.scope.project_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        await self._admit(self.scope)
        return self.scope

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome:
        await self._admit(scope)
        result = await self.foundation.mutate(scope, change_id, mutation)
        self.current()
        return result

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: KnowledgeSyncResolution
    ) -> KnowledgeSyncOutcome:
        await self._admit(scope)
        result = await self.foundation.resolve(scope, change_id, resolution)
        self.current()
        return result

    async def changes(self, scope: KnowledgeSyncScope, after: int, limit: int) -> KnowledgeSyncPage:
        await self._admit(scope)
        result = await self.foundation.changes(scope, after, limit)
        self.current()
        return result

    async def conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        await self._admit(scope)
        result = await self.foundation.conflict(scope, conflict_id)
        self.current()
        return result

    async def mutate_graph(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: GraphSyncMutation
    ) -> KnowledgeSyncOutcome:
        await self._admit(scope)
        result = await self.graph_foundation.mutate_graph(scope, change_id, mutation)
        self.current()
        return result

    async def resolve_graph(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: GraphSyncResolution
    ) -> KnowledgeSyncOutcome:
        await self._admit(scope)
        result = await self.graph_foundation.resolve_graph(scope, change_id, resolution)
        self.current()
        return result

    async def graph_changes(
        self, scope: KnowledgeSyncScope, after: int, limit: int
    ) -> KnowledgeSyncPage:
        await self._admit(scope)
        result = await self.graph_foundation.graph_changes(scope, after, limit)
        self.current()
        return result

    async def graph_conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        await self._admit(scope)
        result = await self.graph_foundation.graph_conflict(scope, conflict_id)
        self.current()
        return result
