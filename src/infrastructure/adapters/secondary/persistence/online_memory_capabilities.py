"""Advisory write affordances reuse the command authority's live permission checks."""

from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    KnowledgeSyncScope,
    MemorySyncVersion,
)
from src.domain.ports.repositories.online_memory_repository import (
    OnlineMemoryCapabilities,
    OnlineMemoryObjectActions,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_access import (
    authorize_scope,
    authorize_write,
    snapshot,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncEnrollmentModel,
)
from src.infrastructure.adapters.secondary.persistence.models import Memory, UserProject


async def _allowed(
    db: AsyncSession,
    scope: KnowledgeSyncScope,
    member: UserProject,
    current: MemorySyncVersion | None,
    *,
    deleting: bool = False,
) -> bool:
    try:
        await authorize_write(db, scope, member, current, deleting=deleting)
    except KnowledgeSyncError as error:
        if error.code != "knowledge_sync_forbidden":
            raise
        return False
    return True


async def read_online_memory_capabilities(
    db: AsyncSession, actor_id: str, project_id: str, objects: tuple[tuple[str, int], ...]
) -> OnlineMemoryCapabilities | None:
    try:
        project, member = await authorize_scope(db, actor_id, project_id)
    except KnowledgeSyncError as error:
        if error.code != "knowledge_sync_forbidden":
            raise
        return None
    enrollment = await db.scalar(
        select(KnowledgeSyncEnrollmentModel)
        .where(KnowledgeSyncEnrollmentModel.project_id == project_id)
        .execution_options(populate_existing=True)
    )
    if enrollment is None or not enrollment.enabled or enrollment.tenant_id != project.tenant_id:
        return None
    scope = KnowledgeSyncScope(
        tenant_id=project.tenant_id, project_id=project_id, actor_id=actor_id
    )
    can_create = await _allowed(db, scope, member, None)
    output: list[OnlineMemoryObjectActions] = []
    for memory_id, revision in objects:
        memory = await db.scalar(
            select(Memory)
            .where(
                Memory.id == memory_id,
                Memory.project_id == project_id,
                Memory.version == revision,
            )
            .execution_options(populate_existing=True)
        )
        if memory is None or not 1 <= memory.version < MAX_REVISION:
            continue
        current = snapshot(memory)
        actions: list[Literal["update", "delete"]] = []
        if await _allowed(db, scope, member, current):
            actions.append("update")
        if await _allowed(db, scope, member, current, deleting=True):
            actions.append("delete")
        output.append(
            OnlineMemoryObjectActions(
                memory_id=memory_id, revision=revision, allowed_actions=tuple(actions)
            )
        )
    return OnlineMemoryCapabilities(
        tenant_id=scope.tenant_id,
        project_id=scope.project_id,
        actor_id=actor_id,
        allowed_actions=("create",) if can_create else (),
        objects=tuple(output),
    )
