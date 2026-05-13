"""SQL repository for the blackboard transactional outbox."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import WorkspaceBlackboardOutboxModel


class SqlBlackboardOutboxRepository:
    """Durable queue for blackboard SSE event publishing.

    Items are enqueued inside the same DB transaction as the originating
    mutation (post/reply/file create/update/delete). A background
    dispatcher drains pending rows, publishes them to Redis, then marks
    them dispatched. Failed dispatches are retried with exponential
    backoff up to ``max_attempts`` before moving to ``dead_letter``.
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self._db = db

    async def enqueue(
        self,
        *,
        workspace_id: str,
        tenant_id: str,
        project_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        max_attempts: int = 10,
    ) -> WorkspaceBlackboardOutboxModel:
        """Append a pending outbox item; flush so the caller-level commit
        atomically persists both the mutation and the event row.
        """
        item = WorkspaceBlackboardOutboxModel(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            tenant_id=tenant_id,
            project_id=project_id,
            event_type=event_type,
            payload_json=dict(payload or {}),
            metadata_json=dict(metadata or {}),
            correlation_id=correlation_id,
            status="pending",
            attempt_count=0,
            max_attempts=max_attempts,
        )
        self._db.add(item)
        await self._db.flush()
        return item

    async def get_by_id(self, outbox_id: str) -> WorkspaceBlackboardOutboxModel | None:
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspaceBlackboardOutboxModel).where(
                    WorkspaceBlackboardOutboxModel.id == outbox_id
                )
            )
        )
        return result.scalar_one_or_none()

    async def list_by_workspace(
        self,
        workspace_id: str,
        *,
        limit: int = 50,
    ) -> list[WorkspaceBlackboardOutboxModel]:
        if limit <= 0:
            return []
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspaceBlackboardOutboxModel)
                .where(WorkspaceBlackboardOutboxModel.workspace_id == workspace_id)
                .order_by(
                    WorkspaceBlackboardOutboxModel.created_at.desc(),
                    WorkspaceBlackboardOutboxModel.id.desc(),
                )
                .limit(limit)
            )
        )
        return list(result.scalars().all())

    async def claim_due(
        self,
        *,
        limit: int,
        now: datetime | None = None,
    ) -> list[WorkspaceBlackboardOutboxModel]:
        """Claim a batch of due-to-publish items.

        Unlike the workspace-plan outbox (which has long-running handlers
        and uses leases), blackboard publish is sub-second and idempotent;
        we skip leasing and rely on row-level locks via ``FOR UPDATE
        SKIP LOCKED`` so multiple dispatchers can run safely.
        """
        if limit <= 0:
            return []

        current_time = now or datetime.now(UTC)
        due_for_attempt = or_(
            WorkspaceBlackboardOutboxModel.next_attempt_at.is_(None),
            WorkspaceBlackboardOutboxModel.next_attempt_at <= current_time,
        )
        pending_or_failed_due = and_(
            WorkspaceBlackboardOutboxModel.status.in_(("pending", "failed")),
            due_for_attempt,
        )
        stmt = (
            select(WorkspaceBlackboardOutboxModel)
            .where(
                WorkspaceBlackboardOutboxModel.attempt_count
                < WorkspaceBlackboardOutboxModel.max_attempts,
                pending_or_failed_due,
            )
            .order_by(
                WorkspaceBlackboardOutboxModel.created_at.asc(),
                WorkspaceBlackboardOutboxModel.id.asc(),
            )
            .limit(limit)
        )
        # SKIP LOCKED is a no-op on SQLite (test env); harmless on Postgres.
        try:
            stmt = stmt.with_for_update(skip_locked=True)
        except Exception:
            stmt = stmt.with_for_update()
        result = await self._db.execute(refresh_select_statement(stmt))
        items = list(result.scalars().all())
        for item in items:
            item.attempt_count = int(item.attempt_count) + 1
        await self._db.flush()
        return items

    async def mark_dispatched(
        self,
        outbox_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        item = await self.get_by_id(outbox_id)
        if item is None:
            return False
        item.status = "dispatched"
        item.dispatched_at = now or datetime.now(UTC)
        item.last_error = None
        item.next_attempt_at = None
        await self._db.flush()
        return True

    async def mark_failed(
        self,
        outbox_id: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        item = await self.get_by_id(outbox_id)
        if item is None:
            return False
        current_time = now or datetime.now(UTC)
        item.last_error = error_message
        if int(item.attempt_count) >= int(item.max_attempts):
            item.status = "dead_letter"
            item.next_attempt_at = None
        else:
            item.status = "failed"
            backoff_seconds = min(2 ** int(item.attempt_count), 300)
            item.next_attempt_at = current_time + timedelta(seconds=backoff_seconds)
        await self._db.flush()
        return True

    async def purge_dispatched_before(
        self,
        *,
        cutoff: datetime,
        limit: int = 1000,
    ) -> int:
        """Delete dispatched rows older than ``cutoff``; returns count.

        Lets ops bound table growth without a separate scheduled task.
        """
        if limit <= 0:
            return 0
        stmt = refresh_select_statement(
            select(WorkspaceBlackboardOutboxModel)
            .where(
                WorkspaceBlackboardOutboxModel.status == "dispatched",
                WorkspaceBlackboardOutboxModel.dispatched_at.is_not(None),
                WorkspaceBlackboardOutboxModel.dispatched_at < cutoff,
            )
            .limit(limit)
        )
        result = await self._db.execute(stmt
        )
        rows = list(result.scalars().all())
        for row in rows:
            await self._db.delete(row)
        await self._db.flush()
        return len(rows)


__all__ = ["SqlBlackboardOutboxRepository"]
