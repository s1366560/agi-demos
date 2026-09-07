"""Atomic, request-scoped sync foundation, deliberately not mounted in production.

PostgreSQL project row locks order journal allocation and commit. Every operation
rechecks membership. The caller owns the outer commit; savepoints make rejected
operations leave no partial object, cursor, receipt or conflict writes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncResolution,
    KnowledgeSyncScope,
    MemorySyncContent,
    MemorySyncMutation,
    MemorySyncVersion,
    require_change_id,
)
from src.domain.model.knowledge_sync.online_patch import MemoryOnlinePatch
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_access import (
    authorize_scope,
    authorize_write,
    snapshot,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeSyncChangeModel as Change,
    KnowledgeSyncConflictModel as Conflict,
    KnowledgeSyncCursorModel as Cursor,
    KnowledgeSyncReceiptModel as Receipt,
    KnowledgeSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_write_intent import (
    register_write_intent,
)
from src.infrastructure.adapters.secondary.persistence.models import (
    Memory,
    MemoryChunk,
    MemoryShare,
    UserProject,
)


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SqlKnowledgeSyncRepository:
    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self.db = db

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            async with self.db.begin_nested():
                yield
        except IntegrityError as error:
            # Different projects lock different rows but share the global Memory
            # primary key. Reject an insertion race without leaking the winner.
            raise KnowledgeSyncError("knowledge_sync_write_conflict") from error

    async def resolve_scope(self, actor_id: str, project_id: str) -> KnowledgeSyncScope:
        project, _ = await authorize_scope(self.db, actor_id, project_id)
        return KnowledgeSyncScope(
            tenant_id=project.tenant_id, project_id=project.id, actor_id=actor_id
        )

    async def _authorize(self, scope: KnowledgeSyncScope, *, lock: bool = False) -> UserProject:
        project, member = await authorize_scope(
            self.db, scope.actor_id, scope.project_id, lock=lock
        )
        if project.tenant_id != scope.tenant_id:
            raise KnowledgeSyncError("knowledge_sync_forbidden")
        return member

    async def _current(self, scope: KnowledgeSyncScope, memory_id: str) -> MemorySyncVersion | None:
        memory = await self.db.scalar(
            select(Memory)
            .where(Memory.id == memory_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tombstone = await self.db.get(Tombstone, memory_id, populate_existing=True)
        if memory is not None:
            if memory.project_id != scope.project_id or tombstone is not None:
                raise KnowledgeSyncError("knowledge_sync_id_collision")
            return snapshot(memory)
        if tombstone is not None:
            if (tombstone.tenant_id, tombstone.project_id) != (scope.tenant_id, scope.project_id):
                raise KnowledgeSyncError("knowledge_sync_id_collision")
            return MemorySyncVersion.from_dict(tombstone.snapshot)
        return None

    async def _replay(
        self, scope: KnowledgeSyncScope, change_id: str, request: str
    ) -> KnowledgeSyncOutcome | None:
        require_change_id(change_id)
        row = await self.db.get(
            Receipt, (scope.tenant_id, scope.project_id, scope.actor_id, change_id)
        )
        if row is None:
            return None
        if row.request_json != request:
            raise KnowledgeSyncError("knowledge_sync_idempotency_conflict")
        return KnowledgeSyncOutcome(receipt_json=row.receipt_json, replayed=True)

    async def _receipt(
        self, scope: KnowledgeSyncScope, change_id: str, request: str, value: dict[str, Any]
    ) -> KnowledgeSyncOutcome:
        value = {**value, "change_id": change_id}
        encoded = canonical(value)
        self.db.add(
            Receipt(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                actor_id=scope.actor_id,
                change_id=change_id,
                request_json=request,
                receipt_json=encoded,
            )
        )
        await self.db.flush()
        return KnowledgeSyncOutcome(receipt_json=encoded)

    async def mutate(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome:
        return await self._mutate(scope, change_id, mutation, online=False)

    async def mutate_online(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: MemorySyncMutation
    ) -> KnowledgeSyncOutcome:
        """Apply an online CAS command without persisting an offline conflict on rejection.

        Consumers must supply the authenticated actor and the observed revision.
        This primitive neither enrolls a project nor commits the outer transaction.
        """
        return await self._mutate(scope, change_id, mutation, online=True)

    async def mutate_online_patch(
        self, scope: KnowledgeSyncScope, change_id: str, patch: MemoryOnlinePatch
    ) -> KnowledgeSyncOutcome:
        """Replay the original partial command before materializing its full snapshot."""
        request = canonical({"online_patch": patch.to_dict()})
        async with self._transaction():
            member = await self._authorize(scope, lock=True)
            current = await self._current(scope, patch.memory_id)
            await authorize_write(self.db, scope, member, current, deleting=False)
            replay = await self._replay(scope, change_id, request)
            if replay is not None:
                return replay
            if current is None or current.deleted or current.revision != patch.expected_revision:
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
            version = await self._apply(
                scope, patch.memory_id, current, patch.apply(current.content), deleted=False
            )
            memory = await self.db.get(Memory, patch.memory_id, populate_existing=True)
            if memory is None:
                raise KnowledgeSyncError("knowledge_sync_write_conflict")
            # These fields remain outside the portable journal. Capture them in
            # the original receipt so HTTP replay cannot read a later projection.
            retained_fields = {
                "entities": memory.entities,
                "relationships": memory.relationships,
                "collaborators": memory.collaborators,
                "is_public": memory.is_public,
                "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
            }
            return await self._accepted(
                scope, change_id, request, version, retained_fields=retained_fields
            )

    async def _mutate(
        self,
        scope: KnowledgeSyncScope,
        change_id: str,
        mutation: MemorySyncMutation,
        *,
        online: bool,
    ) -> KnowledgeSyncOutcome:
        request = canonical({"online_mutation" if online else "mutation": mutation.to_dict()})
        async with self._transaction():
            member = await self._authorize(scope, lock=True)
            current = await self._current(scope, mutation.memory_id)
            await authorize_write(
                self.db, scope, member, current, deleting=mutation.operation == "delete"
            )
            replay = await self._replay(scope, change_id, request)
            if replay is not None:
                return replay
            if not online:
                pending = await self.db.scalar(
                    select(Conflict.id).where(
                        Conflict.tenant_id == scope.tenant_id,
                        Conflict.project_id == scope.project_id,
                        Conflict.actor_id == scope.actor_id,
                        Conflict.memory_id == mutation.memory_id,
                        Conflict.resolved_change_id.is_(None),
                    )
                )
                if pending is not None:
                    raise KnowledgeSyncError("knowledge_sync_conflict_pending")
            revision = current.revision if current else 0
            if revision != mutation.expected_revision or (current is not None and current.deleted):
                if online:
                    raise KnowledgeSyncError("knowledge_sync_write_conflict")
                conflict_id = str(uuid4())
                self.db.add(
                    Conflict(
                        id=conflict_id,
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        actor_id=scope.actor_id,
                        memory_id=mutation.memory_id,
                        change_id=change_id,
                        proposed=mutation.to_dict(),
                        current=current.to_dict() if current else None,
                    )
                )
                return await self._receipt(
                    scope, change_id, request, {"status": "conflict", "conflict_id": conflict_id}
                )
            version = await self._apply(
                scope,
                mutation.memory_id,
                current,
                mutation.content,
                deleted=mutation.operation == "delete",
            )
            return await self._accepted(scope, change_id, request, version)

    async def _apply(
        self,
        scope: KnowledgeSyncScope,
        memory_id: str,
        current: MemorySyncVersion | None,
        content: MemorySyncContent | None,
        *,
        deleted: bool,
    ) -> MemorySyncVersion:
        revision = current.revision + 1 if current else 1
        if revision > MAX_REVISION or (deleted and current is None):
            raise KnowledgeSyncError("knowledge_sync_revision_invalid")
        content = content or (current.content if current else None)
        if content is None:
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        version = MemorySyncVersion(
            memory_id=memory_id,
            revision=revision,
            deleted=deleted,
            author_id=current.author_id if current else scope.actor_id,
            created_at_ms=current.created_at_ms
            if current
            else int(datetime.now(UTC).timestamp() * 1000),
            content=content,
        )
        await register_write_intent(self.db, scope, memory_id, current, deleted=deleted)
        if deleted:
            _ = await self.db.execute(delete(MemoryShare).where(MemoryShare.memory_id == memory_id))
            _ = await self.db.execute(
                delete(MemoryChunk).where(
                    MemoryChunk.project_id == scope.project_id,
                    MemoryChunk.source_type == "memory",
                    MemoryChunk.source_id == memory_id,
                )
            )
            if current is not None and not current.deleted:
                result = await self.db.scalar(
                    delete(Memory)
                    .where(
                        Memory.id == memory_id,
                        Memory.project_id == scope.project_id,
                        Memory.version == current.revision,
                    )
                    .returning(Memory.id)
                )
                if result != memory_id:
                    raise KnowledgeSyncError("knowledge_sync_resolution_stale")
            tombstone = await self.db.get(Tombstone, memory_id)
            if tombstone is None:
                self.db.add(
                    Tombstone(
                        memory_id=memory_id,
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        revision=revision,
                        snapshot=version.to_dict(),
                    )
                )
            else:
                tombstone.revision, tombstone.snapshot = revision, version.to_dict()
        else:
            values = {
                "title": content.title,
                "content": content.content,
                "content_type": content.content_type,
                "tags": list(content.tags),
                "meta": json.loads(content.metadata_json),
                "status": content.status,
                "version": revision,
                "processing_status": "PENDING",
            }
            if current is None or current.deleted:
                self.db.add(
                    Memory(
                        id=memory_id,
                        project_id=scope.project_id,
                        author_id=version.author_id,
                        created_at=datetime.fromtimestamp(version.created_at_ms / 1000, UTC),
                        **values,
                    )
                )
            else:
                result = await self.db.scalar(
                    update(Memory)
                    .where(
                        Memory.id == memory_id,
                        Memory.project_id == scope.project_id,
                        Memory.version == current.revision,
                    )
                    .values(**values)
                    .returning(Memory.id)
                )
                if result != memory_id:
                    raise KnowledgeSyncError("knowledge_sync_resolution_stale")
        await self.db.flush()
        if not deleted and current is not None and current.deleted:
            _ = await self.db.execute(delete(Tombstone).where(Tombstone.memory_id == memory_id))
        return version

    async def _accepted(
        self,
        scope: KnowledgeSyncScope,
        change_id: str,
        request: str,
        version: MemorySyncVersion,
        *,
        retained_fields: dict[str, Any] | None = None,
    ) -> KnowledgeSyncOutcome:
        cursor = await self.db.get(
            Cursor, (scope.tenant_id, scope.project_id), populate_existing=True
        )
        if cursor is None:
            cursor = Cursor(tenant_id=scope.tenant_id, project_id=scope.project_id, sequence=0)
            self.db.add(cursor)
        if cursor.sequence >= 2**63 - 1:
            raise KnowledgeSyncError("knowledge_sync_cursor_exhausted")
        cursor.sequence += 1
        self.db.add(
            Change(
                tenant_id=scope.tenant_id,
                project_id=scope.project_id,
                sequence=cursor.sequence,
                actor_id=scope.actor_id,
                change_id=change_id,
                memory_id=version.memory_id,
                revision=version.revision,
                snapshot=version.to_dict(),
            )
        )
        value: dict[str, Any] = {
            "status": "applied",
            "sequence": cursor.sequence,
            "version": version.to_dict(),
        }
        if retained_fields is not None:
            value["retained_fields"] = retained_fields
        return await self._receipt(
            scope,
            change_id,
            request,
            value,
        )

    async def _conflict_row(self, scope: KnowledgeSyncScope, conflict_id: str) -> Conflict:
        require_change_id(conflict_id)
        row = await self.db.scalar(
            select(Conflict)
            .where(
                Conflict.id == conflict_id,
                Conflict.tenant_id == scope.tenant_id,
                Conflict.project_id == scope.project_id,
                Conflict.actor_id == scope.actor_id,
            )
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise KnowledgeSyncError("knowledge_sync_conflict_not_found")
        return row

    async def resolve(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: KnowledgeSyncResolution
    ) -> KnowledgeSyncOutcome:
        request = canonical({"resolution": resolution.to_dict()})
        async with self._transaction():
            member = await self._authorize(scope, lock=True)
            row = await self._conflict_row(scope, resolution.conflict_id)
            current = await self._current(scope, row.memory_id)
            proposed = MemorySyncMutation.from_dict(row.proposed)
            await authorize_write(
                self.db,
                scope,
                member,
                current,
                deleting=resolution.decision == "use_proposed" and proposed.operation == "delete",
            )
            replay = await self._replay(scope, change_id, request)
            if replay is not None:
                return replay
            if row.resolved_change_id is not None:
                raise KnowledgeSyncError("knowledge_sync_conflict_resolved")
            if (current.revision if current else 0) != resolution.expected_current_revision:
                raise KnowledgeSyncError("knowledge_sync_resolution_stale")
            row.resolved_change_id = change_id
            if resolution.decision == "keep_current":
                return await self._receipt(
                    scope,
                    change_id,
                    request,
                    {
                        "status": "resolved",
                        "version": current.to_dict() if current else None,
                        "conflict_id": row.id,
                    },
                )
            content = resolution.content if resolution.decision == "merged" else proposed.content
            deleted = resolution.decision == "use_proposed" and proposed.operation == "delete"
            version = await self._apply(scope, row.memory_id, current, content, deleted=deleted)
            return await self._accepted(scope, change_id, request, version)

    async def changes(self, scope: KnowledgeSyncScope, after: int, limit: int) -> KnowledgeSyncPage:
        _ = await self._authorize(scope)
        cursor = await self.db.get(
            Cursor, (scope.tenant_id, scope.project_id), populate_existing=True
        )
        high = cursor.sequence if cursor else 0
        if (
            type(after) is not int
            or not 0 <= after <= high
            or type(limit) is not int
            or not 1 <= limit <= 500
        ):
            raise KnowledgeSyncError("knowledge_sync_cursor_invalid")
        rows = (
            await self.db.scalars(
                select(Change)
                .where(
                    Change.tenant_id == scope.tenant_id,
                    Change.project_id == scope.project_id,
                    Change.sequence > after,
                    Change.sequence <= high,
                )
                .order_by(Change.sequence)
                .limit(limit + 1)
            )
        ).all()
        page = rows[:limit]
        return KnowledgeSyncPage(
            changes_json=json.dumps(
                [
                    {"sequence": row.sequence, "change_id": row.change_id, "version": row.snapshot}
                    for row in page
                ]
            ),
            next_cursor=page[-1].sequence if page else after,
            has_more=len(rows) > limit,
        )

    async def conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        _ = await self._authorize(scope)
        row = await self._conflict_row(scope, conflict_id)
        observed = await self._current(scope, row.memory_id)
        return {
            "id": row.id,
            "memory_id": row.memory_id,
            "proposed": row.proposed,
            "current": row.current,
            "observed_current": observed.to_dict() if observed else None,
            "resolved_change_id": row.resolved_change_id,
        }
