"""Transaction-local structural intent; authentication stays in the application.

The database guard consumes scope/object/revision facts only. It never derives an
actor from author_id, connection identity, process metadata or this payload.
"""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import KnowledgeSyncScope, MemorySyncVersion


async def register_write_intent(
    db: AsyncSession,
    scope: KnowledgeSyncScope,
    memory_id: str,
    current: MemorySyncVersion | None,
    *,
    deleted: bool,
) -> None:
    if db.get_bind().dialect.name != "postgresql":
        return
    if deleted:
        operation = "delete"
    elif current is None:
        operation = "create"
    elif current.deleted:
        operation = "restore"
    else:
        operation = "update"
    payload = json.dumps(
        {
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "memory_id": memory_id,
            "operation": operation,
            "expected_revision": current.revision if current else 0,
        }
    )
    _ = await db.execute(
        text("SELECT set_config('memstack.knowledge_sync_intent', :payload, true)"),
        {"payload": payload},
    )
