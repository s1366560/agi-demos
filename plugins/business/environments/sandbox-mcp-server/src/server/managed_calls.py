"""Multiplex managed worker calls only within their authenticated WebSocket connection."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

from src.mcp_manager.call_events import progress_sink


class ManagedCalls:
    def __init__(
        self,
        dispatch: Callable[[dict], Awaitable[dict | None]],
        send: Callable[[dict], Awaitable[None]],
    ):
        self.dispatch = dispatch
        self.send = send
        self.pending: dict[int | str, asyncio.Task[None]] = {}

    async def handle(self, data: dict) -> bool:
        method = data.get("method")
        params = data.get("params", {})
        if not isinstance(params, dict):
            return False
        if method == "notifications/cancelled" and "id" not in data:
            key = params.get("requestId")
            if type(key) in (int, str) and (task := self.pending.get(key)) is not None:
                task.cancel()
            return True
        if method != "tools/call" or params.get("name") not in (
            "mcp_server_call_tool",
            "mcp_server_stop",
        ):
            return False
        key = data.get("id")
        if type(key) not in (int, str):
            await self._error(None, -32600, "Invalid worker call id")
        elif key in self.pending:
            await self._error(key, -32600, "Worker call id already in use")
        elif len(self.pending) >= 64:
            await self._error(key, -32000, "Worker call concurrency limit reached")
        else:
            task = asyncio.create_task(self._run(data))
            self.pending[key] = task
            task.add_done_callback(lambda _: self.pending.pop(key, None))
        return True

    async def _run(self, data: dict) -> None:
        meta = data["params"].get("_meta")
        token = meta.get("progressToken") if isinstance(meta, dict) else None

        async def progress(update: dict[str, Any]) -> None:
            await self.send(
                {
                    "jsonrpc": "2.0",
                    "method": "notifications/progress",
                    "params": {**update, "progressToken": token},
                }
            )

        ctx = progress_sink.set(progress if type(token) in (int, str) else None)
        try:
            response = await self.dispatch(data)
            if response is not None:
                await self.send(response)
        except (ConnectionResetError, RuntimeError):
            pass
        finally:
            progress_sink.reset(ctx)

    async def _error(self, key: int | str | None, code: int, message: str) -> None:
        await self.send({"jsonrpc": "2.0", "id": key, "error": {"code": code, "message": message}})

    async def close(self) -> None:
        tasks = list(self.pending.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
