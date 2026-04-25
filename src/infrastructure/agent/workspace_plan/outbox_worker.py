"""Durable worker loop for workspace plan outbox jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import WorkspacePlanOutboxModel
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)

logger = logging.getLogger(__name__)

WorkspacePlanOutboxHandler = Callable[[WorkspacePlanOutboxModel, AsyncSession], Awaitable[None]]
WorkspacePlanOutboxEventPublisher = Callable[[dict[str, Any]], Awaitable[None]]
WorkspacePlanSessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]


class WorkspacePlanOutboxWorker:
    """Poll, lease, and process durable workspace plan jobs.

    Handlers are registered by ``event_type`` so the production runtime can wire
    dispatch, verification, projection, and supervisor-tick jobs independently.
    The worker owns transaction boundaries around claim/complete/fail; handlers
    should perform their work with the provided session and raise on failure.
    """

    def __init__(
        self,
        *,
        session_factory: WorkspacePlanSessionFactory,
        handlers: Mapping[str, WorkspacePlanOutboxHandler],
        worker_id: str | None = None,
        poll_interval_seconds: float = 2.0,
        batch_size: int = 10,
        lease_seconds: int = 60,
        event_publisher: WorkspacePlanOutboxEventPublisher | None = None,
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._handlers = dict(handlers)
        self._worker_id = worker_id or f"workspace-plan-outbox-{uuid.uuid4()}"
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self._event_publisher = event_publisher
        self._task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def worker_id(self) -> str:
        return self._worker_id

    def start(self) -> None:
        """Start the polling loop."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._poll_loop(), name=f"{self._worker_id}:poll")
        logger.info("workspace plan outbox worker started: %s", self._worker_id)

    async def stop(self) -> None:
        """Stop the polling loop."""
        self._running = False
        if self._task is not None and not self._task.done():
            _ = self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        self._task = None
        logger.info("workspace plan outbox worker stopped: %s", self._worker_id)

    async def run_once(self) -> int:
        """Claim one batch and process it synchronously.

        Returns the number of claimed items. Tests and one-shot maintenance jobs
        can use this without starting a background task.
        """
        async with self._session_factory() as session:
            repo = SqlWorkspacePlanOutboxRepository(session)
            claimed = await repo.claim_due(
                limit=self._batch_size,
                lease_owner=self._worker_id,
                lease_seconds=self._lease_seconds,
            )
            claimed_ids = [item.id for item in claimed]
            await session.commit()

        for outbox_id in claimed_ids:
            await self._process_claimed(outbox_id)
        return len(claimed_ids)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                _ = await self.run_once()
                await asyncio.sleep(self._poll_interval_seconds)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("workspace plan outbox worker poll failed")
                await asyncio.sleep(self._poll_interval_seconds)

    async def _process_claimed(self, outbox_id: str) -> None:
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspacePlanOutboxRepository(session)
                item = await repo.get_by_id(outbox_id)
                if item is None:
                    return
                if item.status != "processing" or item.lease_owner != self._worker_id:
                    return
                handler = self._handlers.get(item.event_type)
                if handler is None:
                    marked = await repo.mark_failed(
                        outbox_id,
                        f"no handler for event_type={item.event_type}",
                    )
                    payload = (
                        _outbox_update_payload(item, "outbox_handler_missing") if marked else None
                    )
                    await session.commit()
                    if payload is not None:
                        await self._publish_outbox_update(payload)
                    return

                await handler(item, session)
                marked = await repo.mark_completed(outbox_id)
                payload = _outbox_update_payload(item, "outbox_completed") if marked else None
                await session.commit()
                if payload is not None:
                    await self._publish_outbox_update(payload)
        except Exception as exc:
            await self._mark_failed_cleanly(outbox_id, str(exc))

    async def _mark_failed_cleanly(self, outbox_id: str, error_message: str) -> None:
        payload: dict[str, Any] | None = None
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspacePlanOutboxRepository(session)
                item = await repo.get_by_id(outbox_id)
                marked = await repo.mark_failed(outbox_id, error_message)
                if marked and item is not None:
                    payload = _outbox_update_payload(item, "outbox_failed")
                await session.commit()
        except Exception:
            logger.exception("failed to mark workspace plan outbox item failed: %s", outbox_id)
            return
        if payload is not None:
            await self._publish_outbox_update(payload)

    async def _publish_outbox_update(self, payload: dict[str, Any]) -> None:
        if self._event_publisher is None:
            return
        try:
            await self._event_publisher(payload)
        except Exception:
            logger.warning(
                "workspace plan outbox update event publish failed",
                exc_info=True,
                extra={
                    "workspace_id": payload.get("workspace_id"),
                    "plan_id": payload.get("plan_id"),
                    "outbox_id": payload.get("outbox_id"),
                },
            )


def _outbox_update_payload(item: WorkspacePlanOutboxModel, change: str) -> dict[str, Any]:
    item_payload = dict(item.payload_json or {})
    payload: dict[str, Any] = {
        "workspace_id": item.workspace_id,
        "plan_id": item.plan_id,
        "outbox_id": item.id,
        "outbox_event_type": item.event_type,
        "outbox_status": item.status,
        "attempt_count": item.attempt_count,
        "max_attempts": item.max_attempts,
        "change": change,
    }
    node_id = item_payload.get("node_id")
    if isinstance(node_id, str) and node_id:
        payload["node_id"] = node_id
    if item.last_error:
        payload["last_error"] = item.last_error
    return payload


__all__ = [
    "WorkspacePlanOutboxEventPublisher",
    "WorkspacePlanOutboxHandler",
    "WorkspacePlanOutboxWorker",
    "WorkspacePlanSessionFactory",
]
