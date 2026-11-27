"""Stdio command guest. The parent process is the only host port."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Awaitable, Callable  # noqa: TC003
from typing import Any

from plugins.business.agent.guest.binding import RPC_LINE_LIMIT, CommandError, Progress, bind, reset
from plugins.business.agent.guest.dispatch import OPERATIONS, TOOLS

_PROGRESS: Callable[[dict[str, Any]], Awaitable[None]] | None = None


def _write(payload: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, separators=(",", ":")) + "\n")
    sys.stdout.flush()


class RpcPort:
    def __init__(
        self, reader: asyncio.StreamReader, user_id: str, tenant_id: str, project_id: str | None
    ) -> None:
        self.reader = reader
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
                events.append(message["data"])
                future.events = events  # type: ignore[attr-defined]
            return
        future = self._pending.pop(message["id"], None)
        if future is not None and not future.done():
            future.set_result(message)

    async def _call(
        self, method: str, params: dict[str, Any], progress: Progress | None = None
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
                elif _PROGRESS is not None:
                    await _PROGRESS(event)
            if future.done():
                break
            await asyncio.sleep(0)
            if not future.done():
                await asyncio.wait({future}, timeout=0.01)
        message = future.result()
        if not message.get("ok", False):
            raise CommandError(
                str(message.get("code") or "runtime_unavailable"),
                str(message.get("message") or "host call failed"),
            )
        return message.get("output")

    async def http(self, method: str, path: str, **kwargs: object) -> dict[str, Any]:
        return await self._call("http", {"method": method, "path": path, **kwargs})

    async def own(self, conversation_id: str) -> None:
        await self._call("own", {"conversation_id": conversation_id})

    async def local_ids(self, ids: list[str]) -> list[str]:
        return list(await self._call("local_ids", {"ids": ids}))

    async def meta(self, conversation_id: str) -> dict[str, Any] | None:
        return await self._call("meta", {"conversation_id": conversation_id})

    async def placements(self, ids: list[str]) -> dict[str, str]:
        return dict(await self._call("placements", {"ids": ids}))

    async def run_cloud(self, run_id: str, conversation_id: str) -> bool:
        return bool(
            await self._call("run_cloud", {"run_id": run_id, "conversation_id": conversation_id})
        )

    async def run_conversation(self, run_id: str) -> str | None:
        return await self._call("run_conversation", {"run_id": run_id})

    async def run_fields(self, run_id: str, conversation_id: str) -> dict[str, Any]:
        return await self._call(
            "run_fields", {"run_id": run_id, "conversation_id": conversation_id}
        )

    async def device(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("device", {"op": op, "payload": payload})

    async def stream(self, message: dict[str, Any], progress: Progress | None) -> dict[str, Any]:
        return await self._call("stream", {"message": message}, progress)

    async def actor(self, action: str) -> str:
        return str(await self._call("actor", {"action": action}))

    async def voice(self, conversation_id: str) -> dict[str, str]:
        return await self._call("voice", {"conversation_id": conversation_id})

    async def welcome(self, complete: bool | None) -> dict[str, Any]:
        return await self._call("welcome", {"complete": complete})

    async def model_routes(self) -> dict[str, Any]:
        return await self._call("model_routes", {})

    async def lifecycle_snapshot(self) -> dict[str, Any]:
        return await self._call("lifecycle_snapshot", {})

    async def templates(self, limit: int) -> list[dict[str, Any]]:
        return list(await self._call("templates", {"limit": limit}))

    async def hitl(self, conversation_id: str, request_id: str) -> dict[str, Any] | None:
        return await self._call(
            "hitl", {"conversation_id": conversation_id, "request_id": request_id}
        )

    async def attachment_files(
        self, conversation_id: str, ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        return dict(
            await self._call("attachment_files", {"conversation_id": conversation_id, "ids": ids})
        )

    async def attachment(self, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("attachment", {"payload": payload})

    async def dashboard(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("dashboard", {"op": op, "payload": payload})

    async def tenant_sessions(self, op: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call("tenant_sessions", {"op": op, "payload": payload})


async def _run(start: dict[str, Any], reader: asyncio.StreamReader) -> None:
    global _PROGRESS
    operation = start.get("operation")
    if start.get("tool"):
        operation = TOOLS.get(start["tool"], operation)
    handler = OPERATIONS.get(operation or "")
    if handler is None:
        _write({"type": "result", "ok": False, "code": "forbidden", "message": "unknown command"})
        return
    port = RpcPort(
        reader,
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
        {
            "tenant_id": port.tenant_id,
            "project_id": port.project_id,
            "user_id": port.user_id,
            "id": port.user_id,
        },
    )()
    ctx = type("Ctx", (), {"scope": scope, "user": scope})()
    token = bind(port)

    async def publish(frame: dict[str, Any]) -> None:
        _write({"type": "progress", "data": frame})

    _PROGRESS = publish
    try:
        output = await handler(ctx, start.get("payload") or {}, publish)
    except CommandError as exc:
        _write({"type": "result", "ok": False, "code": exc.code, "message": str(exc)})
    except Exception as exc:
        _write({"type": "result", "ok": False, "code": "runtime_unavailable", "message": str(exc)})
    else:
        _write({"type": "result", "ok": True, "output": output})
    finally:
        reset(token)
        _PROGRESS = None
        pumping.cancel()


async def main() -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=RPC_LINE_LIMIT)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
    line = await reader.readline()
    if not line:
        return
    await _run(json.loads(line), reader)


if __name__ == "__main__":
    asyncio.run(main())
