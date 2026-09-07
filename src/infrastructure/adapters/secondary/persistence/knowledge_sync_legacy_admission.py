"""Legacy admission shares the repository transaction through its final commit.

NO KEY UPDATE excludes bootstrap's UPDATE lock while allowing external graph
sessions to acquire the KEY SHARE locks required by project foreign keys.
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project


async def admit_legacy_memory_write(
    session: AsyncSession,
    *,
    project_id: str | None = None,
    memory_id: str | None = None,
    tenant_id: str | None = None,
) -> None:
    with session.no_autoflush:
        actual = None
        if memory_id is not None:
            actual = await session.scalar(select(Memory.project_id).where(Memory.id == memory_id))
            if actual is None:
                actual = await session.scalar(
                    select(Tombstone.project_id).where(Tombstone.memory_id == memory_id)
                )
        if actual is not None and project_id is not None and actual != project_id:
            raise KnowledgeSyncError("knowledge_sync_write_conflict")
        project_id = actual or project_id
        if project_id is None:
            # Never grant a lease without a project: a later read could observe
            # a newly created enrolled memory with this formerly absent ID.
            if memory_id is not None:
                raise KnowledgeSyncError("knowledge_sync_memory_not_found")
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        project = await session.scalar(
            select(Project)
            .where(Project.id == project_id)
            .with_for_update(key_share=True)
            .execution_options(populate_existing=True)
        )
        if project is None or (tenant_id is not None and tenant_id != project.tenant_id):
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        enrollment = await session.scalar(
            select(Enrollment)
            .where(Enrollment.project_id == project_id)
            .with_for_update(read=True)
            .execution_options(populate_existing=True)
        )
        if enrollment is None:
            raise KnowledgeSyncError("knowledge_sync_fence_missing")
        if enrollment.tenant_id != project.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        if enrollment.enabled:
            raise KnowledgeSyncError("knowledge_sync_write_context_required")
        if memory_id is not None:
            current = await session.scalar(select(Memory.project_id).where(Memory.id == memory_id))
            if current is not None and current != project_id:
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
