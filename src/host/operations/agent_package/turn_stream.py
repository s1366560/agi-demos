"""Open the host agent socket for one admitted command, without the caller's bearer."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager, suppress
from typing import Any, cast

from src.host.operations.agent_package.admission import admit
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


def project_message(event: dict[str, Any], run_id: str) -> dict[str, Any] | None:
    if event.get("run_id") != run_id:
        return None
    kind, data = event.get("type"), event.get("data", {})
    if kind == "text_delta" and isinstance(data.get("delta"), str):
        return {"type": "text_delta", "text": data["delta"]}
    if kind == "assistant_message" and isinstance(data.get("content"), str):
        return {"type": "assistant_message", "text": data["content"]}
    if kind == "thought" and isinstance(data.get("thought"), str):
        return {"type": "thought", "text": data["thought"]}
    if kind in {"complete", "cancelled", "agent_stopped"}:
        return {"type": "complete"}
    return None


@asynccontextmanager
async def _actor_socket(
    app: Callable[..., Awaitable[None]], user_id: str, tenant_id: str
) -> AsyncIterator[tuple[asyncio.Task[None], asyncio.Queue[Any], asyncio.Queue[Any]]]:
    scope: dict[str, Any] = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "scheme": "ws",
        "path": "/api/v1/agent/ws",
        "raw_path": b"/api/v1/agent/ws",
        "query_string": b"",
        "root_path": "",
        "http_version": "1.1",
        "subprotocols": [],
        "headers": [],
        "server": ("localhost", 80),
        "client": ("127.0.0.1", 0),
        "app": app,
    }
    incoming: asyncio.Queue[Any] = asyncio.Queue()
    outgoing: asyncio.Queue[Any] = asyncio.Queue(maxsize=16)
    incoming.put_nowait({"type": "websocket.connect"})
    with admit(user_id, tenant_id):
        pending = cast(
            Coroutine[Any, Any, None], app(scope, incoming.get, outgoing.put)
        )
        socket: asyncio.Task[None] = asyncio.create_task(pending)
        try:
            yield socket, incoming, outgoing
        finally:
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
            with suppress(TimeoutError):
                await asyncio.wait_for(socket, 3)


async def _next_event(socket: asyncio.Task[None], outgoing: asyncio.Queue[Any]) -> dict[str, Any]:
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


async def stream_turn(
    app: Callable[..., Awaitable[None]],
    *,
    user_id: str,
    tenant_id: str,
    project_id: str,
    data: dict[str, Any],
    progress: Progress | None,
) -> dict[str, Any]:
    async with _actor_socket(app, user_id, tenant_id) as (socket, incoming, outgoing):
        run_id = ""
        while True:
            event = await _next_event(socket, outgoing)
            kind = event.get("type")
            if kind == "connected":
                if event.get("data", {}).get("user_id") != user_id:
                    raise OptionalBusinessError("forbidden", "Agent socket identity mismatch")
                turn = {
                    "type": "send_message",
                    "project_id": project_id,
                    "execution_target": "cloud",
                    **data,
                }
                incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(turn)})
                continue
            if event.get("conversation_id") != data["conversation_id"]:
                continue
            if kind == "error" and (not event.get("run_id") or event["run_id"] == run_id):
                raise OptionalBusinessError(
                    "apply_failed", "Cloud Agent denied or failed this turn"
                )
            if kind == "ack" and event.get("message_id") == data["message_id"]:
                run_id = event["run_id"]
                receipt = {"type": "accepted", "run_id": run_id, "revision": event["run_revision"]}
                if progress:
                    await progress(receipt)
                if event.get("replayed"):
                    return {**receipt, "replayed": True}
                continue
            projected = project_message(event, run_id) if run_id else None
            if projected is not None:
                if projected["type"] == "complete":
                    return {"run_id": run_id, "status": "complete"}
                if progress:
                    await progress(projected)


async def actor_control(
    app: Callable[..., Awaitable[None]], *, user_id: str, tenant_id: str, project_id: str, action: str
) -> str:
    if action not in {"stop_agent", "restart_agent"}:
        raise OptionalBusinessError("forbidden", "Unsupported actor action")
    async with _actor_socket(app, user_id, tenant_id) as (socket, incoming, outgoing):
        connected = await _next_event(socket, outgoing)
        if connected.get("type") != "connected" or connected.get("data", {}).get("user_id") != (
            user_id
        ):
            raise OptionalBusinessError("forbidden", "Agent socket identity mismatch")
        frame = {"type": action, "project_id": project_id}
        incoming.put_nowait({"type": "websocket.receive", "text": json.dumps(frame)})
        while True:
            event = await _next_event(socket, outgoing)
            if (
                event.get("type") == "agent_lifecycle_ack"
                and event.get("action") == action
                and event.get("project_id") == project_id
            ):
                status = event.get("status")
                if status == "not_found":
                    raise OptionalBusinessError("conflict", "Project actor no longer exists")
                if not isinstance(status, str) or status not in ("restarted", "stopping"):
                    raise OptionalBusinessError("apply_failed", "Unexpected actor response")
                return status
