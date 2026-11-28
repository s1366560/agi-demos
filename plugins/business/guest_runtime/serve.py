"""Stdio command guest. The parent process is the only host port."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import HTTPException

from plugins.business.guest_runtime.binding import (
    RPC_LINE_LIMIT,
    CommandError,
    Progress,
    bind,
    reset,
)
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

Handler = Callable[[Any, dict[str, Any], Progress | None], Awaitable[dict[str, Any]]]


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class RpcPort:
    def __init__(self, user_id: str, tenant_id: str, project_id: str | None) -> None:
        self.user_id = user_id
        self.tenant_id = tenant_id
        self.project_id = project_id
        self._next = 1
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}

    def feed(self, message: dict[str, Any]) -> None:
        if message.get("type") == "event":
            future = self._pending.get(message["id"])
            if future is not None and not future.done():
                events: list[dict[str, Any]] = getattr(future, "events", [])
                events.append(message.get("data") or {})
                future.events = events  # type: ignore[attr-defined]
            return
        future = self._pending.pop(message["id"], None)
        if future is not None and not future.done():
            future.set_result(message)

    async def _call(
        self,
        method: str,
        params: dict[str, Any],
        progress: Progress | None = None,
    ) -> object:
        call_id = self._next
        self._next += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        future.events = []  # type: ignore[attr-defined]
        self._pending[call_id] = future
        _write({"type": "call", "id": call_id, "method": method, "params": params})
        while not future.done():
            events = list(getattr(future, "events", []))
            future.events = []  # type: ignore[attr-defined]
            for event in events:
                if progress is not None:
                    await progress(event)
            if future.done():
                break
            await asyncio.sleep(0)
            if not future.done():
                await asyncio.wait({future}, timeout=0.01)
        pending = list(getattr(future, "events", []))
        future.events = []  # type: ignore[attr-defined]
        for event in pending:
            if progress is not None:
                await progress(event)
        message = future.result()
        if not message.get("ok", False):
            raise CommandError(
                str(message.get("code") or "runtime_unavailable"),
                str(message.get("message") or "host call failed"),
            )
        return message.get("output")

    async def call(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        output = await self._call("call", {"name": name, "payload": payload})
        if not isinstance(output, dict):
            raise CommandError("runtime_unavailable", "host capability returned no object")
        return output

    async def http(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        query: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        output = await self._call(
            "http",
            {"method": method, "path": path, "body": body, "query": query, "headers": headers},
        )
        if not isinstance(output, dict):
            raise CommandError("runtime_unavailable", "host route returned no object")
        return output

    async def data(
        self,
        name: str,
        params: dict[str, Any],
        progress: Progress | None = None,
    ) -> dict[str, Any]:
        output = await self._call("data", {"name": name, "params": params}, progress)
        if not isinstance(output, dict):
            raise CommandError("runtime_unavailable", "host data returned no object")
        return output


def _error(code: str, message: str) -> None:
    _write({"type": "result", "ok": False, "code": code, "message": message})


async def _run(
    start: dict[str, Any], operations: dict[str, Handler], reader: asyncio.StreamReader
) -> None:
    allowed = {"operation", "payload", "user_id", "tenant_id", "project_id"}
    if not set(start) <= allowed:
        _error("forbidden", "unexpected guest input")
        return
    handler = operations.get(str(start.get("operation") or ""))
    if handler is None:
        _error("forbidden", "unknown command")
        return
    port = RpcPort(
        user_id=str(start["user_id"]),
        tenant_id=str(start["tenant_id"]),
        project_id=start.get("project_id"),
    )

    async def pump() -> None:
        while True:
            line = await reader.readline()
            if not line:
                return
            port.feed(json.loads(line))

    pumping = asyncio.create_task(pump())
    scope = type(
        "Scope",
        (),
        {"tenant_id": port.tenant_id, "project_id": port.project_id, "user_id": port.user_id},
    )()
    ctx = type("Ctx", (), {"scope": scope, "user": scope})()
    token = bind(port)

    async def publish(frame: dict[str, Any]) -> None:
        _write({"type": "progress", "data": frame})

    try:
        output = await handler(ctx, start.get("payload") or {}, publish)
    except CommandError as exc:
        _error(exc.code, str(exc))
    except OptionalBusinessError as exc:
        _error(exc.code, str(exc))
    except HTTPException as exc:
        code = {401: "forbidden", 403: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
            exc.status_code, "runtime_unavailable"
        )
        _error(code, str(exc.detail))
    except Exception as exc:
        _error("runtime_unavailable", str(exc))
    else:
        _write({"type": "result", "ok": True, "output": output})
    finally:
        reset(token)
        pumping.cancel()


def main(operations: dict[str, Handler]) -> None:
    async def _entry() -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader(limit=RPC_LINE_LIMIT)
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        line = await reader.readline()
        if not line:
            return
        await _run(json.loads(line), operations, reader)

    asyncio.run(_entry())
