"""Owned cleanup tasks whose lifetime is independent of any awaiting caller."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True, kw_only=True)
class _LifecycleOutcomeV2:
    error: BaseException | None = None


_pending_lifecycle_tasks: set[asyncio.Task[_LifecycleOutcomeV2]] = set()


class OwnedLifecycleTaskV2:
    """Run cleanup once, shielding physical work and preserving its original failure."""

    def __init__(
        self,
        operation: Callable[[], Awaitable[None]],
        *,
        name: str,
    ) -> None:
        self._operation = operation
        self._name = name
        self._task: asyncio.Task[_LifecycleOutcomeV2] | None = None

    @property
    def started(self) -> bool:
        """Whether ownership of cleanup has already transferred to its task."""
        return self._task is not None

    def start(self) -> None:
        """Start once and retain the task even when all external owners are dropped."""
        if self._task is not None:
            return
        task = asyncio.create_task(self._run(), name=self._name)
        self._task = task
        _pending_lifecycle_tasks.add(task)
        task.add_done_callback(_pending_lifecycle_tasks.discard)

    async def wait(self) -> None:
        """Observe cached completion without forwarding caller cancellation to cleanup."""
        self.start()
        task = self._task
        if task is None:
            raise RuntimeError("lifecycle task did not start")
        outcome = await asyncio.shield(task)
        if outcome.error is not None:
            raise outcome.error

    async def _run(self) -> _LifecycleOutcomeV2:
        try:
            await self._operation()
        except BaseException as error:
            # A disposer may itself raise CancelledError. Returning an outcome
            # keeps that distinct from cancellation of a shielded waiting caller.
            return _LifecycleOutcomeV2(error=error)
        return _LifecycleOutcomeV2()
