"""Project-lifetime ownership for detached SubAgent asyncio tasks."""

from __future__ import annotations

import asyncio
from collections.abc import Coroutine, Mapping
from contextvars import Context
from types import MappingProxyType
from typing import Any

from src.infrastructure.plugins.v2.runtime_context import RuntimeV2Error


class DetachedSubAgentTaskSupervisor:
    """Own detached run tasks across individual ``ReActAgent`` instances."""

    def __init__(self) -> None:
        super().__init__()
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._closed = False
        self._shutdown_task: asyncio.Task[None] | None = None

    @property
    def is_closed(self) -> bool:
        """Return whether the supervisor has permanently closed registration."""
        return self._closed

    @property
    def tasks(self) -> Mapping[str, asyncio.Task[Any]]:
        """Expose a read-only live view for compatibility and diagnostics."""
        return MappingProxyType(self._tasks)

    def task_for(self, run_id: str) -> asyncio.Task[Any] | None:
        """Return the task currently owned for ``run_id``."""
        return self._tasks.get(run_id)

    def create_task(
        self,
        *,
        run_id: str,
        coroutine: Coroutine[Any, Any, Any],
        name: str,
        context: Context | None = None,
    ) -> asyncio.Task[Any]:
        """Create and atomically register one detached task.

        Registration is synchronous with respect to the event loop. ``shutdown`` closes the
        registration gate before its first await, so a task can never be omitted from the
        shutdown snapshot after it has been accepted.
        """
        if self._closed:
            coroutine.close()
            raise RuntimeV2Error(
                "detached_subagent_supervisor_closed",
                "detached SubAgent task supervisor is shutting down",
            )
        if run_id in self._tasks:
            coroutine.close()
            raise ValueError(f"Run {run_id} is already running")

        task = asyncio.create_task(coroutine, name=name, context=context)
        self._tasks[run_id] = task
        task.add_done_callback(lambda completed: self._on_task_done(run_id, completed))
        return task

    def cancel(self, run_id: str) -> bool:
        """Request cancellation for an owned run without dropping ownership."""
        task = self._tasks.get(run_id)
        if task is None or task.done():
            return False
        _ = task.cancel()
        return True

    def discard(self, run_id: str, task: asyncio.Task[Any]) -> None:
        """Forget ``task`` only when it is still the task registered for ``run_id``."""
        if self._tasks.get(run_id) is task:
            _ = self._tasks.pop(run_id, None)

    async def shutdown(self) -> None:
        """Close registration, cancel every owned task, and await complete cleanup."""
        if self._shutdown_task is None:
            self._closed = True
            self._shutdown_task = asyncio.create_task(
                self._cancel_and_wait(),
                name="detached-subagent-supervisor-shutdown",
            )
        await asyncio.shield(self._shutdown_task)

    async def _cancel_and_wait(self) -> None:
        tasks = tuple(self._tasks.values())
        for task in tasks:
            if not task.done():
                _ = task.cancel()
        if tasks:
            _ = await asyncio.gather(*tasks, return_exceptions=True)
        for run_id, task in tuple(self._tasks.items()):
            if task.done():
                self.discard(run_id, task)

    def _on_task_done(self, run_id: str, task: asyncio.Task[Any]) -> None:
        self.discard(run_id, task)
        if task.cancelled():
            return
        _ = task.exception()
