"""ACP stdio bridge for MemStack."""

from __future__ import annotations

import asyncio
import logging
import os
import sys
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import cast
from urllib.parse import urlparse, urlunparse

import orjson
import websockets
from acp.exceptions import RequestError

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class BridgeState:
    pending_request_ids: set[object] = field(default_factory=set)
    close_request_ids: set[object] = field(default_factory=set)
    pending_changed: asyncio.Event = field(default_factory=asyncio.Event)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=os.environ.get("LOG_LEVEL", "WARNING"))
    try:
        asyncio.run(run_stdio_bridge())
    except KeyboardInterrupt:
        return


async def run_stdio_bridge() -> None:
    api_key = os.environ.get("ACP_API_KEY") or os.environ.get("MEMSTACK_API_KEY")
    base_url = os.environ.get("ACP_HTTP_BASE_URL") or os.environ.get(
        "MEMSTACK_API_URL",
        "http://127.0.0.1:8000",
    )
    if not api_key:
        await _reject_all_stdin(RequestError.auth_required({"env": "ACP_API_KEY"}))
        return

    websocket_url = _acp_websocket_url(base_url)
    headers = {"Authorization": f"Bearer {api_key}"}
    state = BridgeState()
    try:
        async with websockets.connect(websocket_url, additional_headers=headers) as websocket:
            incoming = asyncio.create_task(_stdin_to_websocket(websocket, state))
            outgoing = asyncio.create_task(_websocket_to_stdout(websocket, state))
            done, _pending = await asyncio.wait({incoming, outgoing}, return_when=asyncio.FIRST_COMPLETED)

            if incoming in done and not outgoing.done():
                await _wait_for_pending_responses(state)
                await websocket.close()
                await asyncio.gather(outgoing, return_exceptions=True)
            else:
                incoming.cancel()
                await asyncio.gather(incoming, return_exceptions=True)

            for task in done:
                task.result()
    except Exception as exc:
        logger.error("ACP stdio bridge disconnected: %s", exc)
        await _try_reject_all_stdin(
            RequestError.internal_error({"details": "ACP backend unavailable"})
        )


async def _stdin_to_websocket(websocket: websockets.ClientConnection, state: BridgeState) -> None:
    async for line in _stdin_lines():
        line = _inject_default_project_id(line)
        request_id, method = _request_metadata(line)
        if request_id is not None:
            state.pending_request_ids.add(request_id)
            if method == "session/close":
                state.close_request_ids.add(request_id)
            state.pending_changed.set()
        await websocket.send(line.rstrip("\n"))


async def _websocket_to_stdout(websocket: websockets.ClientConnection, state: BridgeState) -> None:
    async for message in websocket:
        response_id = _response_id(str(message))
        exit_after_write = response_id in state.close_request_ids and _exit_on_session_close()
        if response_id is not None:
            state.pending_request_ids.discard(response_id)
            state.close_request_ids.discard(response_id)
            state.pending_changed.set()
        sys.stdout.write(str(message).rstrip("\n") + "\n")
        sys.stdout.flush()
        if exit_after_write:
            return


async def _stdin_lines() -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    try:
        transport, _ = await loop.connect_read_pipe(lambda: protocol, sys.stdin.buffer)
    except (AttributeError, NotImplementedError, RuntimeError, ValueError):
        while True:
            try:
                line = await asyncio.to_thread(sys.stdin.readline)
            except ValueError:
                return
            if not line:
                return
            yield line
    else:
        try:
            while line_bytes := await reader.readline():
                yield line_bytes.decode("utf-8")
        finally:
            transport.close()


async def _wait_for_pending_responses(state: BridgeState) -> None:
    timeout_seconds = float(os.environ.get("ACP_STDIO_DRAIN_TIMEOUT_SECONDS", "5"))
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while state.pending_request_ids:
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            logger.warning(
                "ACP stdio bridge closing with %d pending request(s)",
                len(state.pending_request_ids),
            )
            return
        state.pending_changed.clear()
        try:
            await asyncio.wait_for(state.pending_changed.wait(), timeout=remaining)
        except TimeoutError:
            logger.warning(
                "ACP stdio bridge timed out with %d pending request(s)",
                len(state.pending_request_ids),
            )
            return


async def _reject_all_stdin(error: RequestError) -> None:
    async for line in _stdin_lines():
        request_id = _request_id(line)
        if request_id is None:
            continue
        payload = {"jsonrpc": "2.0", "id": request_id, "error": error.to_error_obj()}
        sys.stdout.write(orjson.dumps(payload).decode("utf-8") + "\n")
        sys.stdout.flush()


async def _try_reject_all_stdin(error: RequestError) -> None:
    try:
        await _reject_all_stdin(error)
    except (BrokenPipeError, OSError, RuntimeError, ValueError):
        logger.debug("ACP stdio bridge could not reject pending stdin requests", exc_info=True)


def _request_id(line: str) -> object | None:
    return _request_metadata(line)[0]


def _request_metadata(line: str) -> tuple[object | None, str | None]:
    try:
        message = orjson.loads(line)
    except orjson.JSONDecodeError:
        return None, None
    if isinstance(message, dict) and "id" in message:
        method = message.get("method")
        return cast(object, message["id"]), method if isinstance(method, str) else None
    return None, None


def _inject_default_project_id(line: str) -> str:
    project_id = os.environ.get("ACP_DEFAULT_PROJECT_ID")
    if not project_id:
        return line

    try:
        message = orjson.loads(line)
    except orjson.JSONDecodeError:
        return line

    if not isinstance(message, dict) or message.get("method") != "session/new":
        return line
    params = message.get("params")
    if not isinstance(params, dict):
        return line

    meta = params.get("_meta")
    meta_dict = dict(meta) if isinstance(meta, dict) else {}
    memstack = meta_dict.get("memstack")
    memstack_dict = dict(memstack) if isinstance(memstack, dict) else {}
    if memstack_dict.get("projectId"):
        return line

    memstack_dict["projectId"] = project_id
    meta_dict["memstack"] = memstack_dict
    params = dict(params)
    params["_meta"] = meta_dict
    message = dict(message)
    message["params"] = params
    return orjson.dumps(message).decode("utf-8") + "\n"


def _response_id(line: str) -> object | None:
    try:
        message = orjson.loads(line)
    except orjson.JSONDecodeError:
        return None
    if isinstance(message, dict) and "id" in message and "method" not in message:
        return cast(object, message["id"])
    return None


def _exit_on_session_close() -> bool:
    return os.environ.get("ACP_STDIO_EXIT_ON_SESSION_CLOSE", "1").lower() not in {
        "0",
        "false",
        "no",
    }


def _acp_websocket_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme in {"ws", "wss"}:
        if parsed.path.rstrip("/").endswith("/api/v1/acp/ws"):
            return base_url
        path = parsed.path.rstrip("/") + "/api/v1/acp/ws"
        return urlunparse(parsed._replace(path=path))
    scheme = "wss" if parsed.scheme == "https" else "ws"
    path = parsed.path.rstrip("/") + "/api/v1/acp/ws"
    return urlunparse(parsed._replace(scheme=scheme, path=path))


if __name__ == "__main__":
    main()
