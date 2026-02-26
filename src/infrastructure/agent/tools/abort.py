"""Abort-aware execution utilities for tool implementations.

Provides helpers for running operations that respect the abort signal
from ToolContext, ensuring tools can be cleanly interrupted.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.infrastructure.agent.tools.context import ToolContext

logger = logging.getLogger(__name__)


__all__ = ["abort_aware_gather", "abort_aware_timeout"]


async def abort_aware_gather[T](
    ctx: ToolContext,
    *coros: Awaitable[T],
    return_exceptions: bool = False,
) -> list[T]:
    """Run multiple coroutines concurrently, aborting all if signal fires.

    Like asyncio.gather but cancels all tasks when ctx.abort_signal is set.

    Args:
        ctx: Tool context with abort signal.
        *coros: Coroutines to run concurrently.
        return_exceptions: If True, exceptions are returned instead of raised.

    Returns:
        List of results in the same order as input coroutines.

    Raises:
        ToolAbortedError: If abort signal fires before all complete.
    """
    from src.infrastructure.agent.tools.context import ToolAbortedError

    if not coros:
        return []

    tasks: list[asyncio.Task[T]] = [asyncio.ensure_future(c) for c in coros]
    abort_task: asyncio.Task[bool] = asyncio.ensure_future(
        ctx.abort_signal.wait(),
    )

    try:
        done, _pending = await asyncio.wait(
            [*tasks, abort_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if abort_task in done:
            _cancel_all(tasks)
            _ = await asyncio.gather(*tasks, return_exceptions=True)
            raise ToolAbortedError("Aborted during concurrent execution")

        # Some tasks finished first. Keep waiting for the rest while
        # monitoring the abort signal.
        remaining = [t for t in tasks if not t.done()]
        while remaining:
            done2, _ = await asyncio.wait(
                [*remaining, abort_task],
                return_when=asyncio.FIRST_COMPLETED,
            )
            if abort_task in done2:
                _cancel_all(tasks)
                _ = await asyncio.gather(*tasks, return_exceptions=True)
                raise ToolAbortedError("Aborted during concurrent execution")
            remaining = [t for t in tasks if not t.done()]

        # All tasks complete -- collect results in order.
        results: list[T] = []
        for t in tasks:
            exc = t.exception()
            if exc is not None and not return_exceptions:
                raise exc
            results.append(t.result())
        return results

    finally:
        _ = abort_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await abort_task


async def abort_aware_timeout[T](
    ctx: ToolContext,
    coro: Awaitable[T],
    timeout_seconds: float,
) -> T:
    """Run a coroutine with both a timeout and abort signal check.

    Args:
        ctx: Tool context with abort signal.
        coro: The coroutine to run.
        timeout_seconds: Maximum seconds to wait.

    Returns:
        The coroutine result.

    Raises:
        ToolAbortedError: If abort signal fires.
        TimeoutError: If timeout exceeded.
    """
    from src.infrastructure.agent.tools.context import ToolAbortedError

    task: asyncio.Task[T] = asyncio.ensure_future(coro)
    abort_task: asyncio.Task[bool] = asyncio.ensure_future(
        ctx.abort_signal.wait(),
    )
    timeout_task: asyncio.Task[None] = asyncio.ensure_future(
        asyncio.sleep(timeout_seconds),
    )

    try:
        done, _ = await asyncio.wait(
            [task, abort_task, timeout_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        if abort_task in done:
            _ = task.cancel()
            _ = await asyncio.gather(task, return_exceptions=True)
            raise ToolAbortedError("Aborted during timed execution")

        if timeout_task in done:
            _ = task.cancel()
            _ = await asyncio.gather(task, return_exceptions=True)
            raise TimeoutError(f"Tool execution timed out after {timeout_seconds}s")

        # Task completed before abort or timeout.
        return task.result()

    finally:
        _ = abort_task.cancel()
        _ = timeout_task.cancel()
        _ = await asyncio.gather(abort_task, timeout_task, return_exceptions=True)


def _cancel_all[T](tasks: list[asyncio.Task[T]]) -> None:
    """Cancel all tasks that have not yet completed."""
    for t in tasks:
        if not t.done():
            _ = t.cancel()
