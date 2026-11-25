"""Bridge one signed cloud chat operation to the full API's authenticated Agent socket."""

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from typing import TYPE_CHECKING, Any

from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

if TYPE_CHECKING:
    from starlette.types import Message, Scope

    from src.host.operations.application_commands import PackageOperationContext, Progress


def _project_message(event: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    if event.get("run_id") != run_id:
        return None
    kind, data = event.get("type"), event.get("data", {})
    if kind == "text_delta" and isinstance(data.get("delta"), str):
        return {"type": "text_delta", "text": data["delta"]}
    if kind == "assistant_message" and isinstance(data.get("content"), str):
        return {"type": "assistant_message", "text": data["content"]}
    if kind in {"complete", "cancelled", "agent_stopped"}:
        return {"type": "complete"}
    return None


@asynccontextmanager
async def _actor_socket(
    ctx: "PackageOperationContext",
) -> AsyncIterator[tuple[asyncio.Task[None], "asyncio.Queue[Message]", "asyncio.Queue[Message]"]]:
    scope: Scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws",
        "path": "/api/v1/agent/ws",
        "raw_path": b"/api/v1/agent/ws",
        "query_string": b"",
        "root_path": "",
        "http_version": "1.1",
        "subprotocols": [],
        "headers": [
            (b"authorization", ctx.request.headers.get("authorization", "").encode("latin-1"))
        ],
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 0),
    }
    incoming: asyncio.Queue[Message] = asyncio.Queue()
    outgoing: asyncio.Queue[Message] = asyncio.Queue(maxsize=16)
    incoming.put_nowait({"type": "websocket.connect"})
    socket = asyncio.create_task(ctx.request.app(scope, incoming.get, outgoing.put))
    try:
        yield socket, incoming, outgoing
    finally:
        incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        with suppress(TimeoutError):
            await asyncio.wait_for(socket, 3)


async def stream_turn(
    ctx: "PackageOperationContext", data: dict[str, Any], progress: "Progress | None"
) -> dict[str, Any]:
    async with _actor_socket(ctx) as (socket, incoming, outgoing):
        return await _read_turn(ctx, data, progress, socket, incoming, outgoing)


async def call_actor_control(ctx: "PackageOperationContext", action: str) -> str:
    if action not in {"stop_agent", "restart_agent"}:
        raise OptionalBusinessError("forbidden", "Unsupported actor action")
    async with _actor_socket(ctx) as (socket, incoming, outgoing):
        connected = await _next_event(socket, outgoing)
        if (
            connected.get("type") != "connected"
            or connected.get("data", {}).get("user_id") != ctx.user.id
        ):
            raise OptionalBusinessError("forbidden", "Agent socket identity mismatch")
        frame = {"type": action, "project_id": ctx.scope.project_id}
        incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})
        while True:
            event = await _next_event(socket, outgoing)
            if (
                event.get("type") == "agent_lifecycle_ack"
                and event.get("action") == action
                and event.get("project_id") == ctx.scope.project_id
            ):
                status = event.get("status")
                if status == "not_found":
                    raise OptionalBusinessError("conflict", "Project actor no longer exists")
                if not isinstance(status, str) or status not in ("restarted", "stopping"):
                    raise OptionalBusinessError("apply_failed", "Unexpected actor response")
                return status


async def _read_turn(
    ctx: "PackageOperationContext",
    data: dict[str, Any],
    progress: "Progress | None",
    socket: asyncio.Task[None],
    incoming: "asyncio.Queue[Message]",
    outgoing: "asyncio.Queue[Message]",
) -> dict[str, Any]:
    run_id = ""
    while True:
        event = await _next_event(socket, outgoing)
        kind = event.get("type")
        if kind == "connected":
            if event.get("data", {}).get("user_id") != ctx.user.id:
                raise OptionalBusinessError("forbidden", "Agent socket identity mismatch")
            turn = {
                "type": "send_message",
                "project_id": ctx.scope.project_id,
                "execution_target": "cloud",
                **data,
            }
            incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(turn)})
            continue
        if event.get("conversation_id") != data["conversation_id"]:
            continue
        if kind == "error" and (not event.get("run_id") or event["run_id"] == run_id):
            raise OptionalBusinessError("apply_failed", "Cloud Agent denied or failed this turn")
        if kind == "ack" and event.get("message_id") == data["message_id"]:
            run_id = event["run_id"]
            receipt = {"type": "accepted", "run_id": run_id, "revision": event["run_revision"]}
            if progress:
                await progress(receipt)
            if event.get("replayed"):
                return {**receipt, "replayed": True}
            continue
        projected = _project_message(event, run_id) if run_id else None
        if projected is not None:
            if projected["type"] == "complete":
                return {"run_id": run_id, "status": "complete"}
            if progress:
                await progress(projected)


async def _next_event(
    socket: asyncio.Task[None], outgoing: "asyncio.Queue[Message]"
) -> dict[str, Any]:
    while True:
        reading = asyncio.create_task(outgoing.get())
        try:
            ready, _ = await asyncio.wait(
                {socket, reading}, timeout=300, return_when=asyncio.FIRST_COMPLETED
            )
            if reading not in ready:
                raise OptionalBusinessError(
                    "runtime_unavailable", "Agent stream closed or timed out"
                )
            message = reading.result()
        finally:
            reading.cancel()
            await asyncio.gather(reading, return_exceptions=True)
        if message["type"] == "websocket.accept":
            continue
        if message["type"] != "websocket.send":
            raise OptionalBusinessError("runtime_unavailable", "Cloud Agent socket unavailable")
        frame = json.loads(message.get("text") or message["bytes"])
        if (
            isinstance(frame, dict)
            and frame.get("type") == "error"
            and not frame.get("conversation_id")
        ):
            raise OptionalBusinessError("apply_failed", "Cloud Agent failed to admit this turn")
        if not isinstance(frame, dict):
            raise OptionalBusinessError("runtime_unavailable", "Invalid Agent socket frame")
        return frame
