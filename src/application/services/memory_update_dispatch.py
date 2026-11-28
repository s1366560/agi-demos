"""Process-local accelerator over the durable memory-update task rows.

The TaskLog written in the save transaction is the queue. ``kick`` only
starts work that is already durable. The periodic recovery pass also picks
up rows committed in other processes, including Ray actors.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from contextvars import Context

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.memory_update_jobs import (
    AcquireStages,
    Extract,
    Index,
    execute_memory_update_job,
    resume_memory_update_jobs,
    stage_provider,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]


class MemoryUpdateDispatcher:
    """Run durable jobs now, and again after this process starts."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        extract: Extract | None = None,
        index: Index | None = None,
        acquire_stages: AcquireStages | None = None,
        stage_timeout_s: float | None = None,
        retry_delay_s: Callable[[int], float] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._acquire_stages = stage_provider(extract, index, acquire_stages)
        self._stage_timeout_s = stage_timeout_s
        self._retry_delay_s = retry_delay_s
        self._tasks: set[asyncio.Task[str | list[str]]] = set()
        self._inflight: set[str] = set()
        self._recovery: asyncio.Task[None] | None = None

    def kick(self, task_id: str) -> None:
        """Start one already committed job without waiting for it."""
        if task_id in self._inflight:
            return
        self._inflight.add(task_id)
        task = asyncio.create_task(
            self._run(task_id),
            name=f"memory-update-{task_id}",
            context=Context(),
        )
        self._tasks.add(task)
        task.add_done_callback(self._finish)

    def start(self, *, interval_seconds: float = 30.0) -> None:
        """Scan immediately, then recover newly committed or previously unavailable jobs."""
        if self._recovery is None:
            self._recovery = asyncio.create_task(
                self._poll(interval_seconds),
                name="memory-update-recovery",
                context=Context(),
            )

    async def _poll(self, interval_seconds: float) -> None:
        while True:
            try:
                await self.resume()
            except Exception as exc:
                logger.warning("memory update recovery failed error_type=%s", type(exc).__name__)
            await asyncio.sleep(interval_seconds)

    async def resume(self) -> list[str]:
        return await resume_memory_update_jobs(
            self._session_factory,
            acquire_stages=self._acquire_stages,
            limit=None,
            stage_timeout_s=self._stage_timeout_s,
        )

    async def join(self) -> None:
        """Wait for the accelerator tasks started so far."""
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            await asyncio.gather(*pending)

    async def aclose(self) -> None:
        if self._recovery is not None:
            self._recovery.cancel()
            await asyncio.gather(self._recovery, return_exceptions=True)
            self._recovery = None
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, task_id: str) -> str:
        try:
            outcome = "missing"
            while True:
                outcome = await execute_memory_update_job(
                    self._session_factory,
                    task_id,
                    acquire_stages=self._acquire_stages,
                    stage_timeout_s=self._stage_timeout_s,
                )
                attempt = await self._pending_attempt(task_id)
                if outcome != "failed" or attempt is None:
                    return outcome
                await asyncio.sleep(self._delay_for_attempt(attempt))
        finally:
            self._inflight.discard(task_id)

    async def _pending_attempt(self, task_id: str) -> int | None:
        from src.application.services.memory_update_jobs import MAX_ATTEMPTS
        from src.infrastructure.adapters.secondary.persistence.models import TaskLog

        session = self._session_factory()
        try:
            task = await session.get(TaskLog, task_id)
            if task is None or task.status != "PENDING":
                return None
            if int(task.retry_count or 0) >= MAX_ATTEMPTS:
                return None
            return int(task.retry_count or 0)
        finally:
            await session.close()

    def _delay_for_attempt(self, attempt: int) -> float:
        from src.infrastructure.agent.retry.policy import RetryPolicy

        if self._retry_delay_s is not None:
            return self._retry_delay_s(attempt)
        return RetryPolicy().calculate_delay(max(attempt, 1)) / 1000

    def _finish(self, task: asyncio.Task[str | list[str]]) -> None:
        self._tasks.discard(task)
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            logger.warning("memory update accelerator stopped error_type=%s", type(error).__name__)


_dispatcher: MemoryUpdateDispatcher | None = None


def install_memory_update_dispatcher(dispatcher: MemoryUpdateDispatcher | None) -> None:
    global _dispatcher
    _dispatcher = dispatcher


def current_memory_update_dispatcher() -> MemoryUpdateDispatcher | None:
    return _dispatcher


def kick_memory_update_job(task_id: str) -> bool:
    """Return whether an in-process accelerator accepted the durable job."""
    dispatcher = _dispatcher
    if dispatcher is None:
        return False
    dispatcher.kick(task_id)
    return True


async def shutdown_memory_update_dispatcher() -> None:
    dispatcher = _dispatcher
    if dispatcher is not None:
        await dispatcher.aclose()
