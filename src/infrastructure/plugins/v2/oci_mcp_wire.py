"""Bounded JSON-lines MCP over the Docker attach multiplexed byte stream."""

from __future__ import annotations

import asyncio
import contextlib
import json
import math
import secrets
import socket
import struct
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, Protocol, cast

if TYPE_CHECKING:
    from src.infrastructure.plugins.v2.oci_mcp_records import RecordCall

_FRAME_LIMIT = 128 * 1024
_MAX_EXCHANGE = 512 * 1024


class _Attachment(Protocol):
    def close(self) -> object: ...


class OciMcpWire:
    def __init__(self, raw: _Attachment) -> None:
        self._raw = raw
        self._socket = cast("socket.socket", getattr(raw, "_sock", raw))
        self._buffer = bytearray()
        self._exchange_bytes = 0
        self._request_id = 0
        self._lock = asyncio.Lock()

    def close(self) -> None:
        with contextlib.suppress(OSError):
            self._socket.shutdown(socket.SHUT_RDWR)
        self._raw.close()

    def _read_exact(self, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = self._socket.recv(size - len(data))
            if not chunk:
                raise ValueError("worker closed its protocol stream")
            data.extend(chunk)
        return bytes(data)

    def _read_message(self) -> dict[str, Any]:
        while b"\n" not in self._buffer:
            header = self._read_exact(8)
            channel, size = struct.unpack(">BxxxI", header)
            self._exchange_bytes += size + 8
            if channel != 1 or size > _FRAME_LIMIT or self._exchange_bytes > _MAX_EXCHANGE:
                raise ValueError("worker exceeded the MCP protocol envelope")
            self._buffer.extend(self._read_exact(size))
            if len(self._buffer) > _FRAME_LIMIT:
                raise ValueError("oversized MCP protocol line")
        pos = self._buffer.index(b"\n")
        raw = self._buffer[:pos]
        del self._buffer[: pos + 1]
        message = json.loads(raw)
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise ValueError("unexpected MCP protocol message")
        return message

    async def _send(self, message: dict[str, Any]) -> None:
        line = json.dumps(
            {"jsonrpc": "2.0", **message}, separators=(",", ":"), allow_nan=False
        ).encode()
        if len(line) > _FRAME_LIMIT:
            raise ValueError("oversized MCP invocation")
        await asyncio.to_thread(self._socket.sendall, line + b"\n")

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"method": method, "params": params})

    async def _record_callback(self, message: dict[str, Any], handler: RecordCall) -> None:
        request_id, method, params = (message.get(k) for k in ("id", "method", "params"))
        if (
            not isinstance(request_id, str)
            or not 1 <= len(request_id) <= 64
            or not isinstance(method, str)
            or not isinstance(params, dict)
        ):
            raise ValueError("invalid worker record request")
        result = await handler(method, params)
        await self._send({"id": request_id, "result": result})

    async def request(
        self,
        method: str,
        params: dict[str, Any],
        on_progress: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        on_record: RecordCall | None = None,
    ) -> dict[str, Any]:
        async with self._lock:
            self._request_id += 1
            key = self._request_id
            self._exchange_bytes = len(self._buffer)
            token = secrets.token_hex(16) if on_progress is not None else None
            if token is not None:
                params = {**params, "_meta": {"progressToken": token}}
            try:
                await self._send({"method": method, "params": params, "id": key})
                callbacks = 0
                while True:
                    message = await asyncio.to_thread(self._read_message)
                    if "method" in message and "id" in message:
                        callbacks += 1
                        if on_record is None or callbacks > 20:
                            raise ValueError("worker host callback is unavailable")
                        await self._record_callback(message, on_record)
                        continue
                    if "id" not in message and message.get("method") == "notifications/progress":
                        if on_progress is not None:
                            await on_progress(_progress(message.get("params"), token))
                        continue
                    if (
                        type(message.get("id")) is not int
                        or message["id"] != key
                        or "method" in message
                    ):
                        raise ValueError("unexpected worker request or response identity")
                    result = message.get("result")
                    if "error" in message or not isinstance(result, dict):
                        raise ValueError("MCP worker returned a protocol error")
                    return result
            except asyncio.CancelledError:
                # The parent removes this dedicated container even when the guest ignores cancel.
                with contextlib.suppress(OSError, TimeoutError):
                    async with asyncio.timeout(0.25):
                        await self.notify("notifications/cancelled", {"requestId": key})
                self.close()
                raise
            except (OSError, RecursionError) as error:
                raise ValueError("worker protocol stream failed") from error


def _progress(params: object, token: str | None) -> dict[str, int | float | str]:
    if not isinstance(params, dict) or params.get("progressToken") != token:
        raise ValueError("invalid worker progress identity")
    data: dict[str, int | float | str] = {}
    for name in ("progress", "total"):
        value = params.get(name)
        if value is None and name == "total":
            continue
        if not (type(value) is int or (type(value) is float and math.isfinite(value))):
            raise ValueError("invalid worker progress counter")
        data[name] = value
    if isinstance(message := params.get("message"), str):
        data["message"] = message[:4096]
    return data
