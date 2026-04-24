"""SQL repository for durable workspace plan outbox records."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.common.base_repository import refresh_select_statement
from src.infrastructure.adapters.secondary.persistence.models import WorkspacePlanOutboxModel


class SqlWorkspacePlanOutboxRepository:
    """Durable queue for autonomous plan progression jobs.

    The outbox is intentionally generic: callers decide whether an item
    represents decomposition, dispatch, verification, projection, or a
    supervisory tick. This repository owns only persistence, leasing, retry,
    and dead-letter state.
    """

    def __init__(self, db: AsyncSession) -> None:
        super().__init__()
        self._db = db

    async def enqueue(
        self,
        *,
        plan_id: str,
        workspace_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        max_attempts: int = 5,
        next_attempt_at: datetime | None = None,
    ) -> WorkspacePlanOutboxModel:
        """Append a pending outbox item."""
        item = WorkspacePlanOutboxModel(
            id=str(uuid.uuid4()),
            plan_id=plan_id,
            workspace_id=workspace_id,
            event_type=event_type,
            payload_json=dict(payload or {}),
            metadata_json=dict(metadata or {}),
            status="pending",
            attempt_count=0,
            max_attempts=max_attempts,
            next_attempt_at=next_attempt_at,
        )
        self._db.add(item)
        await self._db.flush()
        return item

    async def get_by_id(self, outbox_id: str) -> WorkspacePlanOutboxModel | None:
        """Return one outbox item by ID."""
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspacePlanOutboxModel).where(WorkspacePlanOutboxModel.id == outbox_id)
            )
        )
        return result.scalar_one_or_none()

    async def claim_due(
        self,
        *,
        limit: int,
        lease_owner: str,
        lease_seconds: int = 60,
        now: datetime | None = None,
    ) -> list[WorkspacePlanOutboxModel]:
        """Claim pending/retryable items and expired leases for one worker."""
        if limit <= 0:
            return []

        current_time = now or datetime.now(UTC)
        lease_expires_at = current_time + timedelta(seconds=lease_seconds)
        due_for_attempt = or_(
            WorkspacePlanOutboxModel.next_attempt_at.is_(None),
            WorkspacePlanOutboxModel.next_attempt_at <= current_time,
        )
        pending_or_failed_due = and_(
            WorkspacePlanOutboxModel.status.in_(("pending", "failed")),
            due_for_attempt,
        )
        expired_processing_lease = and_(
            WorkspacePlanOutboxModel.status == "processing",
            WorkspacePlanOutboxModel.lease_expires_at.is_not(None),
            WorkspacePlanOutboxModel.lease_expires_at <= current_time,
        )
        result = await self._db.execute(
            refresh_select_statement(
                select(WorkspacePlanOutboxModel)
                .where(
                    WorkspacePlanOutboxModel.attempt_count < WorkspacePlanOutboxModel.max_attempts,
                    or_(pending_or_failed_due, expired_processing_lease),
                )
                .order_by(
                    WorkspacePlanOutboxModel.created_at.asc(),
                    WorkspacePlanOutboxModel.id.asc(),
                )
                .limit(limit)
                .with_for_update()
            )
        )
        items = list(result.scalars().all())
        for item in items:
            item.status = "processing"
            item.attempt_count = int(item.attempt_count) + 1
            item.lease_owner = lease_owner
            item.lease_expires_at = lease_expires_at
            item.next_attempt_at = None
            item.last_error = None
        await self._db.flush()
        return items

    async def mark_completed(
        self,
        outbox_id: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Mark a claimed outbox item as completed."""
        item = await self.get_by_id(outbox_id)
        if item is None or item.status != "processing":
            return False

        item.status = "completed"
        item.lease_owner = None
        item.lease_expires_at = None
        item.last_error = None
        item.next_attempt_at = None
        item.processed_at = now or datetime.now(UTC)
        await self._db.flush()
        return True

    async def mark_failed(
        self,
        outbox_id: str,
        error_message: str,
        *,
        now: datetime | None = None,
    ) -> bool:
        """Release a claimed item for retry, or move it to dead letter."""
        item = await self.get_by_id(outbox_id)
        if item is None or item.status != "processing":
            return False

        current_time = now or datetime.now(UTC)
        item.lease_owner = None
        item.lease_expires_at = None
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


__all__ = ["SqlWorkspacePlanOutboxRepository"]
