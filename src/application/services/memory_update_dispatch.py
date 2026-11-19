"""Process-local accelerator over the durable memory-update task rows.

The TaskLog written in the save transaction is the queue. ``kick`` only
starts work that is already durable. Startup and agent initialization call
``resume`` so a restarted process continues rows whose in-process task died.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession

from src.application.services.memory_update_jobs import (
    Extract,
    Index,
    execute_memory_update_job,
    resume_memory_update_jobs,
)

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AsyncSession]
ReadyCheck = Callable[[], bool]


class MemoryUpdateDispatcher:
    """Run durable jobs now, and again after this process starts."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        extract: Extract,
        index: Index,
        stage_timeout_s: float | None = None,
        ready: ReadyCheck | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._extract = extract
        self._index = index
        self._stage_timeout_s = stage_timeout_s
        self._ready = ready
        self._tasks: set[asyncio.Task[str | list[str]]] = set()
        self._inflight: set[str] = set()

    def kick(
        self,
        task_id: str,
        *,
        extract: Extract | None = None,
        index: Index | None = None,
    ) -> None:
        """Start one already committed job without waiting for it."""
        if task_id in self._inflight:
            return
        self._inflight.add(task_id)
        task = asyncio.create_task(
            self._run(task_id, extract or self._extract, index or self._index),
            name=f"memory-update-{task_id}",
        )
        self._tasks.add(task)
        task.add_done_callback(self._finish)

    def resume_soon(self) -> None:
        """Schedule a recovery pass. Rows stay pending when the runtime is not bound."""
        if self._ready is not None and not self._ready():
            return
        task = asyncio.create_task(self.resume(), name="memory-update-resume")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def resume(self) -> list[str]:
        if self._ready is not None and not self._ready():
            return []
        return await resume_memory_update_jobs(
            self._session_factory,
            extract=self._extract,
            index=self._index,
            stage_timeout_s=self._stage_timeout_s,
        )

    async def join(self) -> None:
        """Wait for the accelerator tasks started so far."""
        pending = [task for task in self._tasks if not task.done()]
        if pending:
            await asyncio.gather(*pending)

    async def aclose(self) -> None:
        pending = [task for task in self._tasks if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def _run(self, task_id: str, extract: Extract, index: Index) -> str:
        try:
            return await execute_memory_update_job(
                self._session_factory,
                task_id,
                extract=extract,
                index=index,
                stage_timeout_s=self._stage_timeout_s,
            )
        finally:
            self._inflight.discard(task_id)

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


def kick_memory_update_job(
    task_id: str,
    *,
    extract: Extract | None = None,
    index: Index | None = None,
) -> bool:
    """Return whether an in-process accelerator accepted the durable job."""
    dispatcher = _dispatcher
    if dispatcher is None:
        return False
    dispatcher.kick(task_id, extract=extract, index=index)
    return True


def schedule_memory_update_recovery() -> bool:
    dispatcher = _dispatcher
    if dispatcher is None:
        return False
    dispatcher.resume_soon()
    return True


async def shutdown_memory_update_dispatcher() -> None:
    dispatcher = _dispatcher
    if dispatcher is not None:
        await dispatcher.aclose()
