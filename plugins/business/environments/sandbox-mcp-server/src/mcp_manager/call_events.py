"""Bounded progress delivery for a single managed tool invocation."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Awaitable, Callable
from contextvars import ContextVar
from typing import Any

ProgressSink = Callable[[dict[str, Any]], Awaitable[None]]
progress_sink: ContextVar[ProgressSink | None] = ContextVar("mcp_progress_sink", default=None)


class WorkerProgress:
    """A slow client can coalesce progress updates without stalling the worker's stdout."""

    def __init__(self, send: ProgressSink):
        self._updates: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=1)
        self._send = send
        self._pump = asyncio.create_task(self._forward())

    def offer(self, params: dict[str, Any]) -> None:
        progress = params.get("progress")
        if not self._number(progress):
            return
        update = {"progress": progress}
        if self._number(total := params.get("total")):
            update["total"] = total
        if isinstance(message := params.get("message"), str):
            update["message"] = message[:4096]
        if self._updates.full():
            self._updates.get_nowait()
            self._updates.task_done()
        self._updates.put_nowait(update)

    @staticmethod
    def _number(value: object) -> bool:
        return type(value) is int or (type(value) is float and math.isfinite(value))

    async def _forward(self) -> None:
        while True:
            update = await self._updates.get()
            try:
                await self._send(update)
            except (OSError, RuntimeError):
                pass  # The enclosing WebSocket call owns disconnection handling.
            finally:
                self._updates.task_done()

    async def close(self, *, flush: bool) -> None:
        try:
            if flush:
                async with asyncio.timeout(1):
                    await self._updates.join()
        except TimeoutError:
            pass
        finally:
            self._pump.cancel()
            await asyncio.gather(self._pump, return_exceptions=True)
