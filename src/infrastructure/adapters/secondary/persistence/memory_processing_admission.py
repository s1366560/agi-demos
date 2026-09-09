"""Transaction leases for legacy graph effects that outlive request commits."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncError
from src.domain.model.memory.processing import MemoryProcessingSource
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel as Enrollment,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, Project
from src.infrastructure.adapters.secondary.persistence.sql_memory_repository import (
    SqlMemoryRepository,
)


@asynccontextmanager
async def legacy_graph_write(
    sessions: async_sessionmaker[AsyncSession],
    *,
    project_id: str | None,
    tenant_id: str | None = None,
    memory_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Keep the existing project/enrollment fence until all external effects exit.

    The effect's own sessions may commit independently; they must not acquire
    another project mutation lease while this outer lease is held.
    """
    if not project_id:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    async with (
        sessions() as session,
        session.begin(),
        SqlMemoryRepository(session).legacy_write(
            project_id=project_id, tenant_id=tenant_id, memory_id=memory_id
        ),
    ):
        yield session


async def graph_write_lease_kind(
    sessions: async_sessionmaker[AsyncSession], *, project_id: str
) -> str:
    """Select the pipeline admission for a project without holding any lock.

    Enrollment only flips from disabled to enabled, and each admission
    revalidates the flag under its own lease, so this peek is safe.
    """
    async with sessions() as session:
        enabled = await session.scalar(
            select(Enrollment.enabled).where(Enrollment.project_id == project_id)
        )
    return "derived" if enabled else "legacy"


@asynccontextmanager
async def derived_graph_write(
    sessions: async_sessionmaker[AsyncSession],
    *,
    project_id: str | None,
    tenant_id: str | None = None,
    memory_id: str | None = None,
) -> AsyncIterator[AsyncSession]:
    """Pipeline admission for enrolled projects, fenced by the sync authority.

    Legacy content writers are rejected once a project enrolls; the extraction
    pipeline is a derived writer and keeps working. The KEY SHARE project row
    lock preserves the legacy serialization against sync mutations for the
    whole effect, while the journal's own NO KEY UPDATE lock orders record
    allocation inside the completion transaction without self-deadlocking.
    """
    if not project_id:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    async with sessions() as session, session.begin():
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
        if not enrollment.enabled:
            raise KnowledgeSyncError("knowledge_sync_write_context_required")
        if memory_id is not None:
            current = await session.scalar(select(Memory.project_id).where(Memory.id == memory_id))
            if current is not None and current != project_id:
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
        yield session


async def require_processing_source(
    session: AsyncSession,
    source: MemoryProcessingSource | None,
    *,
    episode_uuid: str,
    content: str,
) -> Memory:
    """Reject stale, removed or substituted jobs before any graph/model call."""
    if source is None or source.memory_id != episode_uuid:
        raise KnowledgeSyncError("knowledge_sync_write_conflict")
    memory = await session.scalar(select(Memory).where(Memory.id == source.memory_id))
    if (
        memory is None
        or memory.project_id != source.project_id
        or memory.version != source.revision
        or memory.task_id != source.task_id
        or memory.content != content
    ):
        raise KnowledgeSyncError("knowledge_sync_write_conflict")
    return memory


async def canonical_graph_tenant(session: AsyncSession, project_id: str) -> str:
    tenant = await session.scalar(select(Project.tenant_id).where(Project.id == project_id))
    if not isinstance(tenant, str) or not tenant:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    return tenant
