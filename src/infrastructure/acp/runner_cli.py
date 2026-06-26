"""Outbound ACP runner process for self-hosted or Kubernetes runner pools."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import orjson
import websockets

from src.infrastructure.acp.client import (
    ExternalACPAgentConfig,
    ExternalACPTransport,
    StdioExternalACPTransport,
    WebSocketExternalACPTransport,
)

logger = logging.getLogger(__name__)


class RunnerWebSocket(Protocol):
    async def send(self, message: str) -> None:
        ...


@dataclass(slots=True)
class RunnerSession:
    session_id: str
    remote_session_id: str
    transport: ExternalACPTransport


class ACPRunnerRuntime:
    """Executes external ACP transports on behalf of the MemStack control plane."""

    def __init__(self, *, runner_id: str, max_sessions: int) -> None:
        self.runner_id = runner_id
        self.max_sessions = max_sessions
        self.sessions: dict[str, RunnerSession] = {}

    def register_payload(self) -> dict[str, Any]:
        return {
            "type": "runner/register",
            "runnerId": self.runner_id,
            "version": "0.1.0",
            "maxSessions": self.max_sessions,
            "currentSessions": len(self.sessions),
            "capabilities": {
                "transports": ["stdio", "websocket"],
                "labels": _labels_from_env(),
                "cwdRoots": _csv_env("ACP_RUNNER_CWD_ROOTS"),
                "allowedCommands": _csv_env("ACP_RUNNER_ALLOWED_COMMANDS"),
            },
        }

    def heartbeat_payload(self) -> dict[str, Any]:
        return {
            "type": "runner/heartbeat",
            "runnerId": self.runner_id,
            "status": "ready",
            "version": "0.1.0",
            "maxSessions": self.max_sessions,
            "currentSessions": len(self.sessions),
            "capabilities": self.register_payload()["capabilities"],
        }

    async def handle_request(self, message: dict[str, Any]) -> dict[str, Any]:
        message_type = message.get("type")
        payload = message.get("payload")
        if not isinstance(payload, dict):
            raise ValueError("runner request payload must be an object")
        if message_type == "session/new":
            return await self._new_session(payload)
        if message_type == "session/prompt":
            return await self._prompt(payload)
        if message_type == "session/cancel":
            await self._cancel(payload)
            return {"ok": True}
        if message_type == "session/close":
            await self._close(payload)
            return {"ok": True}
        raise ValueError(f"unknown runner request type: {message_type}")

    async def _new_session(self, payload: dict[str, Any]) -> dict[str, Any]:
        if len(self.sessions) >= self.max_sessions:
            raise RuntimeError("runner session capacity exceeded")
        session_id = _required_string(payload, "sessionId")
        config_payload = payload.get("config")
        if not isinstance(config_payload, dict):
            raise ValueError("session/new requires config")
        config = ExternalACPAgentConfig.model_validate(config_payload)
        _validate_local_policy(config=config, cwd=_required_string(payload, "cwd"))
        transport = _build_local_transport(config)
        await transport.initialize()
        remote_session_id = await transport.new_session(
            cwd=_required_string(payload, "cwd"),
            additional_directories=_optional_string_list(payload.get("additionalDirectories")),
            mcp_servers=_dict_list(payload.get("mcpServers")),
            field_meta=payload.get("_meta") if isinstance(payload.get("_meta"), dict) else None,
        )
        self.sessions[session_id] = RunnerSession(
            session_id=session_id,
            remote_session_id=remote_session_id,
            transport=transport,
        )
        return {"sessionId": session_id, "remoteSessionId": remote_session_id}

    async def _prompt(self, payload: dict[str, Any]) -> dict[str, Any]:
        session = self._require_session(payload)
        prompt = payload.get("prompt")
        if not isinstance(prompt, list):
            raise ValueError("session/prompt requires prompt list")
        result = await session.transport.prompt(
            remote_session_id=session.remote_session_id,
            prompt=[item for item in prompt if isinstance(item, dict)],
            message_id=payload.get("messageId") if isinstance(payload.get("messageId"), str) else None,
        )
        return result.model_dump(mode="json", by_alias=True, exclude_none=True)

    async def _cancel(self, payload: dict[str, Any]) -> None:
        session = self._require_session(payload)
        await session.transport.cancel(session.remote_session_id)

    async def _close(self, payload: dict[str, Any]) -> None:
        session = self._require_session(payload)
        try:
            await session.transport.close(session.remote_session_id)
        finally:
            self.sessions.pop(session.session_id, None)

    def _require_session(self, payload: dict[str, Any]) -> RunnerSession:
        session_id = _required_string(payload, "sessionId")
        session = self.sessions.get(session_id)
        if session is None:
            raise KeyError(f"runner session not found: {session_id}")
        return session


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=os.environ.get("LOG_LEVEL", "INFO"))
    args = _parse_args()
    try:
        asyncio.run(run_runner(args.connect, args.token, args.runner_id, args.max_sessions))
    except KeyboardInterrupt:
        return


async def run_runner(
    connect_url: str,
    token: str,
    runner_id: str | None,
    max_sessions: int,
) -> None:
    runtime = ACPRunnerRuntime(
        runner_id=runner_id or f"{os.uname().nodename}-{uuid.uuid4().hex[:8]}",
        max_sessions=max_sessions,
    )
    headers = {"Authorization": f"Bearer {token}"}
    async with websockets.connect(connect_url, additional_headers=headers) as websocket:
        await _send_json(websocket, runtime.register_payload())
        heartbeat = asyncio.create_task(_heartbeat_loop(websocket, runtime))
        try:
            async for raw_message in websocket:
                message = _loads(raw_message)
                if not isinstance(message, dict):
                    continue
                if message.get("type") in {"runner/registered", "error"}:
                    continue
                request_id = message.get("id")
                if not isinstance(request_id, str):
                    continue
                try:
                    result = await runtime.handle_request(message)
                    await _send_json(
                        websocket,
                        {"type": "response", "id": request_id, "ok": True, "result": result},
                    )
                except Exception as exc:
                    logger.exception("ACP runner request failed")
                    await _send_json(
                        websocket,
                        {"type": "response", "id": request_id, "ok": False, "error": str(exc)},
                    )
        finally:
            heartbeat.cancel()


async def _heartbeat_loop(websocket: RunnerWebSocket, runtime: ACPRunnerRuntime) -> None:
    while True:
        await asyncio.sleep(10)
        await _send_json(websocket, runtime.heartbeat_payload())


async def _send_json(websocket: RunnerWebSocket, payload: dict[str, Any]) -> None:
    await websocket.send(orjson.dumps(payload).decode("utf-8"))


def _build_local_transport(config: ExternalACPAgentConfig) -> ExternalACPTransport:
    if config.transport == "stdio":
        return StdioExternalACPTransport(config)
    return WebSocketExternalACPTransport(config)


def _validate_local_policy(*, config: ExternalACPAgentConfig, cwd: str) -> None:
    allowed_commands = _csv_env("ACP_RUNNER_ALLOWED_COMMANDS")
    if allowed_commands and config.command and config.command not in allowed_commands:
        raise ValueError("ACP runner command is not allowed")
    cwd_roots = _csv_env("ACP_RUNNER_CWD_ROOTS")
    if cwd_roots and not any(cwd == root or cwd.startswith(f"{root.rstrip('/')}/") for root in cwd_roots):
        raise ValueError("ACP runner cwd is outside allowed roots")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MemStack outbound ACP runner")
    parser.add_argument("--connect", default=os.environ.get("ACP_RUNNER_CONNECT_URL"))
    parser.add_argument("--token", default=os.environ.get("ACP_RUNNER_TOKEN"))
    parser.add_argument("--runner-id", default=os.environ.get("ACP_RUNNER_ID"))
    parser.add_argument(
        "--max-sessions",
        type=int,
        default=int(os.environ.get("ACP_RUNNER_MAX_SESSIONS", "1")),
    )
    args = parser.parse_args()
    if not args.connect:
        parser.error("--connect or ACP_RUNNER_CONNECT_URL is required")
    if not args.token:
        parser.error("--token or ACP_RUNNER_TOKEN is required")
    return args


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{key} is required")
    return value


def _optional_string_list(value: object) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        return None
    return [item for item in value if isinstance(item, str)]


def _dict_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _csv_env(name: str) -> list[str]:
    return [item.strip() for item in os.environ.get(name, "").split(",") if item.strip()]


def _labels_from_env() -> dict[str, str]:
    labels: dict[str, str] = {}
    for item in _csv_env("ACP_RUNNER_LABELS"):
        if "=" not in item:
            continue
        key, value = item.split("=", 1)
        labels[key.strip()] = value.strip()
    return labels


def _loads(raw_message: object) -> object:
    if isinstance(raw_message, bytes):
        return orjson.loads(raw_message)
    if isinstance(raw_message, str):
        return orjson.loads(raw_message)
    return None
