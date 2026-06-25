"""Small JSON-RPC helpers for ACP WebSocket transport."""
# ruff: noqa: ANN401

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

import orjson
from acp.exceptions import RequestError
from pydantic import BaseModel, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

JSONRPC_VERSION = "2.0"
JSONRPCHandler = Callable[[str, Any | None, bool], Awaitable[Any | None]]


class ACPWebSocketJSONRPCPeer:
    """Dispatch ACP JSON-RPC messages over a FastAPI WebSocket."""

    def __init__(self, websocket: WebSocket, handler: JSONRPCHandler) -> None:
        self._websocket = websocket
        self._handler = handler
        self._send_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    async def serve(self) -> None:
        """Receive and dispatch JSON-RPC frames until the socket closes."""
        try:
            while True:
                raw_message = await self._websocket.receive_text()
                message = self._parse(raw_message)
                if message is None:
                    continue
                task = asyncio.create_task(self._dispatch(message))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        except WebSocketDisconnect:
            logger.info("[ACP] WebSocket disconnected")
        finally:
            await self.close()

    async def send_notification(self, method: str, params: dict[str, Any] | None = None) -> None:
        await self._send_json({"jsonrpc": JSONRPC_VERSION, "method": method, "params": params or {}})

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _parse(self, raw_message: str) -> dict[str, Any] | None:
        try:
            message = orjson.loads(raw_message)
        except orjson.JSONDecodeError:
            self._tasks.add(asyncio.create_task(self._send_error(None, RequestError.parse_error())))
            return None
        if not isinstance(message, dict):
            self._tasks.add(asyncio.create_task(self._send_error(None, RequestError.invalid_request())))
            return None
        return message

    async def _dispatch(self, message: dict[str, Any]) -> None:
        request_id = message.get("id")
        method = message.get("method")
        if not isinstance(method, str):
            if "id" in message:
                await self._send_error(request_id, RequestError.invalid_request())
            return

        is_notification = "id" not in message
        try:
            result = await self._handler(method, message.get("params"), is_notification)
        except RequestError as exc:
            if not is_notification:
                await self._send_error(request_id, exc)
            return
        except ValidationError as exc:
            if not is_notification:
                await self._send_error(request_id, RequestError.invalid_params({"errors": exc.errors()}))
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("[ACP] Error handling JSON-RPC method %s", method)
            if not is_notification:
                await self._send_error(
                    request_id,
                    RequestError.internal_error({"details": str(exc)}),
                )
            return

        if is_notification:
            return
        await self._send_result(request_id, result)

    async def _send_result(self, request_id: Any, result: Any) -> None:
        if isinstance(result, BaseModel):
            result = result.model_dump(
                mode="json",
                by_alias=True,
                exclude_none=True,
                exclude_unset=True,
            )
        await self._send_json({"jsonrpc": JSONRPC_VERSION, "id": request_id, "result": result})

    async def _send_error(self, request_id: Any, error: RequestError) -> None:
        payload: dict[str, Any] = {"jsonrpc": JSONRPC_VERSION, "id": request_id}
        payload["error"] = error.to_error_obj()
        await self._send_json(payload)

    async def _send_json(self, payload: dict[str, Any]) -> None:
        async with self._send_lock:
            await self._websocket.send_text(orjson.dumps(payload).decode("utf-8"))
