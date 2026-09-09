"""Atomic, request-scoped derived-record sync foundation in PostgreSQL.

Mirrors the memory sync envelope: project row locks order journal allocation,
every operation rechecks membership, and the caller owns the outer commit.
Savepoints make rejected operations leave no partial object, cursor, receipt
or conflict writes. Neo4j never participates; this journal is the durable
portable form of derived entity/relationship records and their provenance.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.domain.model.knowledge_sync.contracts import (
    MAX_REVISION,
    GraphSyncContent,
    GraphSyncMutation,
    GraphSyncResolution,
    GraphSyncVersion,
    KnowledgeSyncError,
    KnowledgeSyncOutcome,
    KnowledgeSyncPage,
    KnowledgeSyncScope,
    require_change_id,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_access import (
    authorize_derived_write,
    authorize_scope,
)
from src.infrastructure.adapters.secondary.persistence.knowledge_sync_models import (
    KnowledgeGraphSyncChangeModel as Change,
    KnowledgeGraphSyncConflictModel as Conflict,
    KnowledgeGraphSyncCursorModel as Cursor,
    KnowledgeGraphSyncObjectModel as GraphObject,
    KnowledgeGraphSyncReceiptModel as Receipt,
    KnowledgeGraphSyncTombstoneModel as Tombstone,
)
from src.infrastructure.adapters.secondary.persistence.models import UserProject


def canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class SqlKnowledgeGraphSyncRepository:
    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self.db = db

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[None]:
        try:
            async with self.db.begin_nested():
                yield
        except IntegrityError as error:
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

    async def _current(self, scope: KnowledgeSyncScope, object_id: str) -> GraphSyncVersion | None:
        row = await self.db.scalar(
            select(GraphObject)
            .where(GraphObject.object_id == object_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        tombstone = await self.db.get(Tombstone, object_id, populate_existing=True)
        if row is not None:
            if (row.tenant_id, row.project_id) != (scope.tenant_id, scope.project_id):
                raise KnowledgeSyncError("knowledge_sync_id_collision")
            return GraphSyncVersion.from_dict(row.payload)
        if tombstone is not None:
            if (tombstone.tenant_id, tombstone.project_id) != (scope.tenant_id, scope.project_id):
                raise KnowledgeSyncError("knowledge_sync_id_collision")
            return GraphSyncVersion.from_dict(tombstone.snapshot)
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

    async def mutate_graph(
        self, scope: KnowledgeSyncScope, change_id: str, mutation: GraphSyncMutation
    ) -> KnowledgeSyncOutcome:
        request = canonical({"graph_mutation": mutation.to_dict()})
        async with self._transaction():
            member = await self._authorize(scope, lock=True)
            current = await self._current(scope, mutation.object_id)
            authorize_derived_write(scope, member, current)
            replay = await self._replay(scope, change_id, request)
            if replay is not None:
                return replay
            pending = await self.db.scalar(
                select(Conflict.id).where(
                    Conflict.tenant_id == scope.tenant_id,
                    Conflict.project_id == scope.project_id,
                    Conflict.actor_id == scope.actor_id,
                    Conflict.object_id == mutation.object_id,
                    Conflict.resolved_change_id.is_(None),
                )
            )
            if pending is not None:
                raise KnowledgeSyncError("knowledge_sync_conflict_pending")
            revision = current.revision if current else 0
            if revision != mutation.expected_revision or (current is not None and current.deleted):
                conflict_id = str(uuid4())
                self.db.add(
                    Conflict(
                        id=conflict_id,
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        actor_id=scope.actor_id,
                        object_id=mutation.object_id,
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
                mutation.object_id,
                current,
                mutation.content,
                deleted=mutation.operation == "delete",
            )
            return await self._accepted(scope, change_id, request, version)

    async def _apply(
        self,
        scope: KnowledgeSyncScope,
        object_id: str,
        current: GraphSyncVersion | None,
        content: GraphSyncContent | None,
        *,
        deleted: bool,
    ) -> GraphSyncVersion:
        revision = current.revision + 1 if current else 1
        if revision > MAX_REVISION or (deleted and current is None):
            raise KnowledgeSyncError("knowledge_sync_revision_invalid")
        content = content or (current.content if current else None)
        if content is None:
            raise KnowledgeSyncError("knowledge_sync_input_invalid")
        version = GraphSyncVersion(
            object_id=object_id,
            revision=revision,
            deleted=deleted,
            author_id=current.author_id if current else scope.actor_id,
            created_at_ms=current.created_at_ms
            if current
            else int(datetime.now(UTC).timestamp() * 1000),
            content=content,
        )
        if deleted:
            if current is not None and not current.deleted:
                result = await self.db.scalar(
                    delete(GraphObject)
                    .where(
                        GraphObject.tenant_id == scope.tenant_id,
                        GraphObject.project_id == scope.project_id,
                        GraphObject.object_id == object_id,
                        GraphObject.revision == current.revision,
                    )
                    .returning(GraphObject.object_id)
                )
                if result != object_id:
                    raise KnowledgeSyncError("knowledge_sync_resolution_stale")
            tombstone = await self.db.get(Tombstone, object_id)
            if tombstone is None:
                self.db.add(
                    Tombstone(
                        object_id=object_id,
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
                "revision": revision,
                "deleted": False,
                "author_id": version.author_id,
                "created_at_ms": version.created_at_ms,
                "payload": version.to_dict(),
            }
            if current is None or current.deleted:
                self.db.add(
                    GraphObject(
                        tenant_id=scope.tenant_id,
                        project_id=scope.project_id,
                        object_id=object_id,
                        **values,
                    )
                )
            else:
                result = await self.db.scalar(
                    update(GraphObject)
                    .where(
                        GraphObject.tenant_id == scope.tenant_id,
                        GraphObject.project_id == scope.project_id,
                        GraphObject.object_id == object_id,
                        GraphObject.revision == current.revision,
                    )
                    .values(**values)
                    .returning(GraphObject.object_id)
                )
                if result != object_id:
                    raise KnowledgeSyncError("knowledge_sync_resolution_stale")
        await self.db.flush()
        if not deleted and current is not None and current.deleted:
            _ = await self.db.execute(delete(Tombstone).where(Tombstone.object_id == object_id))
        return version

    async def _accepted(
        self,
        scope: KnowledgeSyncScope,
        change_id: str,
        request: str,
        version: GraphSyncVersion,
        *,
        receipt_override: dict[str, Any] | None = None,
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
                object_id=version.object_id,
                revision=version.revision,
                snapshot=version.to_dict(),
            )
        )
        value: dict[str, Any] = {
            "status": "applied",
            "sequence": cursor.sequence,
            "version": version.to_dict(),
        }
        if receipt_override is not None:
            value = {**value, **receipt_override}
        return await self._receipt(scope, change_id, request, value)

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

    async def resolve_graph(
        self, scope: KnowledgeSyncScope, change_id: str, resolution: GraphSyncResolution
    ) -> KnowledgeSyncOutcome:
        request = canonical({"graph_resolution": resolution.to_dict()})
        async with self._transaction():
            member = await self._authorize(scope, lock=True)
            row = await self._conflict_row(scope, resolution.conflict_id)
            current = await self._current(scope, row.object_id)
            proposed = GraphSyncMutation.from_dict(row.proposed)
            authorize_derived_write(scope, member, current)
            replay = await self._replay(scope, change_id, request)
            if replay is not None:
                return replay
            if row.resolved_change_id is not None:
                raise KnowledgeSyncError("knowledge_sync_conflict_resolved")
            if (current.revision if current else 0) != resolution.expected_current_revision:
                raise KnowledgeSyncError("knowledge_sync_resolution_stale")
            if resolution.decision == "keep_both" and proposed.content is None:
                raise KnowledgeSyncError("knowledge_sync_input_invalid")
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
            if resolution.decision == "keep_both":
                # The cloud version stays intact; the proposed version survives as
                # a new detached copy whose deterministic id this conflict reserves.
                # The copy is a normal journal change, so every replica converges.
                copy_id = str(uuid5(UUID(row.id), "keep-both-copy"))
                saved = await self._apply(scope, copy_id, None, proposed.content, deleted=False)
                return await self._accepted(
                    scope,
                    change_id,
                    request,
                    saved,
                    receipt_override={
                        "status": "resolved",
                        "version": current.to_dict() if current else None,
                        "conflict_id": row.id,
                        "copy_object_id": copy_id,
                        "copy_version": saved.to_dict(),
                    },
                )
            content = resolution.content if resolution.decision == "merged" else proposed.content
            deleted = resolution.decision == "use_proposed" and proposed.operation == "delete"
            version = await self._apply(scope, row.object_id, current, content, deleted=deleted)
            return await self._accepted(scope, change_id, request, version)

    async def graph_changes(
        self, scope: KnowledgeSyncScope, after: int, limit: int
    ) -> KnowledgeSyncPage:
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

    async def graph_conflict(self, scope: KnowledgeSyncScope, conflict_id: str) -> dict[str, Any]:
        _ = await self._authorize(scope)
        row = await self._conflict_row(scope, conflict_id)
        observed = await self._current(scope, row.object_id)
        return {
            "id": row.id,
            "object_id": row.object_id,
            "proposed": row.proposed,
            "current": row.current,
            "observed_current": observed.to_dict() if observed else None,
            "resolved_change_id": row.resolved_change_id,
        }
