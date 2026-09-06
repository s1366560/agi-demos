"""Keep APScheduler's AnyIO context in one task for its entire resource lifetime."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from src.infrastructure.plugins.v2.lifecycle_tasks import OwnedLifecycleTaskV2

if TYPE_CHECKING:
    from apscheduler import AsyncScheduler


class SchedulerOwner:
    """Callers request readiness and shutdown without entering the scheduler cancel scope."""

    def __init__(self, scheduler: AsyncScheduler) -> None:
        super().__init__()
        self.scheduler = scheduler
        self._ready = asyncio.Event()
        self._stop = asyncio.Event()
        self._finished = False
        self._started = False
        self._task = OwnedLifecycleTaskV2(self._run, name="apscheduler-owner")

    @property
    def finished(self) -> bool:
        return self._finished

    async def start(self) -> AsyncScheduler:
        self._task.start()
        _ = await self._ready.wait()
        if not self._started or self._finished:
            await self._task.wait()
            raise RuntimeError("Scheduler owner stopped before becoming available")
        return self.scheduler

    async def close(self) -> None:
        self._stop.set()
        await self._task.wait()

    async def _run(self) -> None:
        try:
            async with self.scheduler:
                await self.scheduler.start_in_background()
                self._started = True
                self._ready.set()
                _ = await self._stop.wait()
        finally:
            self._finished = True
            self._ready.set()
