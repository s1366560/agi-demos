"""Stdio command guest. The parent process is the only host port."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable
from typing import Any

from plugins.business.guest_runtime.binding import RPC_LINE_LIMIT, CommandError, bind, reset

Handler = Callable[[Any, dict[str, Any], Any], Awaitable[dict[str, Any]]]


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
        future = self._pending.pop(message["id"], None)
        if future is not None and not future.done():
            future.set_result(message)

    async def _call(self, method: str, params: dict[str, Any]) -> object:
        call_id = self._next
        self._next += 1
        loop = asyncio.get_running_loop()
        future: asyncio.Future[dict[str, Any]] = loop.create_future()
        self._pending[call_id] = future
        _write({"type": "call", "id": call_id, "method": method, "params": params})
        message = await future
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
    ) -> dict[str, Any]:
        output = await self._call(
            "http", {"method": method, "path": path, "body": body, "query": query}
        )
        if not isinstance(output, dict):
            raise CommandError("runtime_unavailable", "host route returned no object")
        return output


async def _run(
    start: dict[str, Any], operations: dict[str, Handler], reader: asyncio.StreamReader
) -> None:
    allowed = {"operation", "payload", "user_id", "tenant_id", "project_id"}
    if not set(start) <= allowed:
        _write(
            {
                "type": "result",
                "ok": False,
                "code": "forbidden",
                "message": "unexpected guest input",
            }
        )
        return
    handler = operations.get(str(start.get("operation") or ""))
    if handler is None:
        _write({"type": "result", "ok": False, "code": "forbidden", "message": "unknown command"})
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
    try:
        output = await handler(ctx, start.get("payload") or {}, None)
    except CommandError as exc:
        _write({"type": "result", "ok": False, "code": exc.code, "message": str(exc)})
    except Exception as exc:
        _write({"type": "result", "ok": False, "code": "runtime_unavailable", "message": str(exc)})
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
