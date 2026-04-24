"""Durable worker loop for workspace plan outbox jobs."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager

from sqlalchemy.ext.asyncio import AsyncSession

from src.infrastructure.adapters.secondary.persistence.models import WorkspacePlanOutboxModel
from src.infrastructure.adapters.secondary.persistence.sql_workspace_plan_outbox import (
    SqlWorkspacePlanOutboxRepository,
)

logger = logging.getLogger(__name__)

WorkspacePlanOutboxHandler = Callable[[WorkspacePlanOutboxModel, AsyncSession], Awaitable[None]]
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
    ) -> None:
        super().__init__()
        self._session_factory = session_factory
        self._handlers = dict(handlers)
        self._worker_id = worker_id or f"workspace-plan-outbox-{uuid.uuid4()}"
        self._poll_interval_seconds = poll_interval_seconds
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
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
                    _ = await repo.mark_failed(
                        outbox_id,
                        f"no handler for event_type={item.event_type}",
                    )
                    await session.commit()
                    return

                await handler(item, session)
                _ = await repo.mark_completed(outbox_id)
                await session.commit()
        except Exception as exc:
            await self._mark_failed_cleanly(outbox_id, str(exc))

    async def _mark_failed_cleanly(self, outbox_id: str, error_message: str) -> None:
        try:
            async with self._session_factory() as session:
                repo = SqlWorkspacePlanOutboxRepository(session)
                _ = await repo.mark_failed(outbox_id, error_message)
                await session.commit()
        except Exception:
            logger.exception("failed to mark workspace plan outbox item failed: %s", outbox_id)


__all__ = [
    "WorkspacePlanOutboxHandler",
    "WorkspacePlanOutboxWorker",
    "WorkspacePlanSessionFactory",
]
