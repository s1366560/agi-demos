"""Closed project enrollment with a fenced, atomic snapshot bootstrap.

Project lock precedes the enrollment lock. Memory rows are deliberately read
without FOR UPDATE: a legacy writer may already hold a Memory row while waiting
for the enrollment fence. Acquiring those rows here would reverse the lock order.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    KnowledgeSyncScope,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_access import (
    authorize_scope,
    snapshot,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncCursorModel as Cursor,
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory


class SqlKnowledgeSyncEnrollment:
    """Internal foundation seam; no production route or implicit auto-enrollment."""

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self.db = db

    async def bootstrap(self, scope: KnowledgeSyncScope) -> dict[str, str | int | bool]:
        async with self.db.begin_nested():
            project, member = await authorize_scope(
                self.db, scope.actor_id, scope.project_id, lock=True
            )
            if project.tenant_id != scope.tenant_id or member.role not in {"owner", "admin"}:
                raise KnowledgeSyncError("knowledge_sync_forbidden")
            enrollment = await self._fence(scope)
            if enrollment.enabled:
                return self._result(enrollment, replayed=True)
            cursor = await self.db.get(
                Cursor, (scope.tenant_id, scope.project_id), populate_existing=True
            )
            if cursor is None:
                cursor = Cursor(tenant_id=scope.tenant_id, project_id=scope.project_id, sequence=0)
                self.db.add(cursor)
            collisions = await self.db.scalar(
                select(Tombstone.memory_id)
                .join(Memory, Memory.id == Tombstone.memory_id)
                .where(Tombstone.project_id == scope.project_id)
            )
            if collisions is not None:
                raise KnowledgeSyncError("knowledge_sync_id_collision")
            rows = (
                await self.db.scalars(
                    select(Memory)
                    .where(Memory.project_id == scope.project_id)
                    .order_by(Memory.id)
                    .execution_options(populate_existing=True)
                )
            ).all()
            count = 0
            for memory in rows:
                version = snapshot(memory)
                if not 1 <= version.revision <= MAX_REVISION:
                    raise KnowledgeSyncError("knowledge_sync_revision_invalid")
                prior = await self.db.scalar(
                    select(Change).where(
                        Change.tenant_id == scope.tenant_id,
                        Change.project_id == scope.project_id,
                        Change.memory_id == memory.id,
                        Change.revision == version.revision,
                    )
                )
                if prior is not None:
                    if prior.snapshot != version.to_dict():
                        raise KnowledgeSyncError("knowledge_sync_bootstrap_revision_collision")
                    continue
                if cursor.sequence >= 2**63 - 1:
                    raise KnowledgeSyncError("knowledge_sync_cursor_exhausted")
                cursor.sequence += 1
                self.db.add(
                    Change(
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        sequence=cursor.sequence,
                        actor_id=scope.actor_id,
                        change_id=str(uuid4()),
                        memory_id=memory.id,
                        revision=version.revision,
                        snapshot=version.to_dict(),
                        source_kind="bootstrap",
                    )
                )
                count += 1
            enrollment.enabled = True
            enrollment.bootstrap_actor_id = scope.actor_id
            enrollment.bootstrap_at = datetime.now(UTC)
            enrollment.bootstrap_count = count
            enrollment.bootstrap_cursor = cursor.sequence
            await self.db.flush()
            return self._result(enrollment, replayed=False)

    async def _fence(self, scope: KnowledgeSyncScope) -> Enrollment:
        enrollment = await self.db.scalar(
            select(Enrollment)
            .where(Enrollment.project_id == scope.project_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if enrollment is None:
            if self.db.get_bind().dialect.name == "postgresql":
                raise KnowledgeSyncError("knowledge_sync_fence_missing")
            enrollment = Enrollment(
                project_id=scope.project_id, tenant_id=scope.tenant_id, enabled=False
            )
            self.db.add(enrollment)
        if enrollment.tenant_id != scope.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        return enrollment

    @staticmethod
    def _result(enrollment: Enrollment, *, replayed: bool) -> dict[str, str | int | bool]:
        return {
            "project_id": enrollment.project_id,
            "enabled": enrollment.enabled,
            "bootstrap_count": enrollment.bootstrap_count,
            "next_cursor": enrollment.bootstrap_cursor,
            "replayed": replayed,
        }
