"""Structural membership and object permission checks for the sync repository."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    KnowledgeSyncError,
    KnowledgeSyncScope,
    MemorySyncContent,
    MemorySyncVersion,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryShare,
    Project,
    User,
    UserProject,
    UserTenant,
)


async def authorize_scope(
    db: AsyncSession, actor_id: str, project_id: str, *, lock: bool = False
) -> tuple[Project, UserProject]:
    query = (
        select(Project).where(Project.id == project_id).execution_options(populate_existing=True)
    )
    if lock:
        query = query.with_for_update()
    project = await db.scalar(query)
    user = await db.scalar(select(User).where(User.id == actor_id, User.is_active.is_(True)))
    if project is None or user is None:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    tenant_member = await db.scalar(
        select(UserTenant.id).where(
            UserTenant.tenant_id == project.tenant_id, UserTenant.user_id == actor_id
        )
    )
    member = await db.scalar(
        select(UserProject)
        .where(UserProject.project_id == project_id, UserProject.user_id == actor_id)
        .execution_options(populate_existing=True)
    )
    if tenant_member is None or member is None:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    return project, member


async def authorize_write(
    db: AsyncSession,
    scope: KnowledgeSyncScope,
    member: UserProject,
    current: MemorySyncVersion | None,
) -> None:
    if member.role not in {"owner", "admin", "member"}:
        raise KnowledgeSyncError("knowledge_sync_forbidden")
    if current is None or current.author_id == scope.actor_id or member.role in {"owner", "admin"}:
        return
    shares = (
        await db.scalars(
            select(MemoryShare).where(
                MemoryShare.memory_id == current.memory_id,
                MemoryShare.shared_with_user_id == scope.actor_id,
                or_(MemoryShare.expires_at.is_(None), MemoryShare.expires_at > datetime.now(UTC)),
            )
        )
    ).all()
    if not any(share.permissions.get("edit") is True for share in shares):
        raise KnowledgeSyncError("knowledge_sync_forbidden")


def snapshot(memory: Memory) -> MemorySyncVersion:
    created = memory.created_at
    if created.tzinfo is None:
        created = created.replace(tzinfo=UTC)
    return MemorySyncVersion(
        memory_id=memory.id,
        revision=memory.version,
        deleted=False,
        author_id=memory.author_id,
        created_at_ms=int(created.timestamp() * 1000),
        content=MemorySyncContent(
            title=memory.title,
            content=memory.content,
            content_type=memory.content_type,
            tags=tuple(memory.tags or ()),
            metadata_json=json.dumps(memory.meta or {}),
            status=memory.status,
        ),
    )
