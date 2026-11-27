"""Run one agent command in a child process that cannot see the caller token."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from plugins.business.agent.guest.binding import RPC_LINE_LIMIT
from plugins.business.agent.guest.dispatch import TOOLS
from src.host.operations.agent_package.bridge import HostBridge
from src.host.operations.application_commands import PackageOperationContext
from src.host.operations.tenant_commands import TenantPackageContext
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]


class _Command(Protocol):
    tool: str
    host_operation: str | None


_ROOT = Path(__file__).resolve().parents[4]
_KNOWN = set(TOOLS.values()) | set(TOOLS)


def guest_operation(plugin_id: str, command: _Command) -> str | None:
    """Return the agent operation when this command must leave the host process."""
    if plugin_id != "memstack-agent":
        return None
    if command.tool in TOOLS:
        return TOOLS[command.tool]
    operation = command.host_operation
    if operation is not None and operation in _KNOWN and operation.startswith("app.agent."):
        return operation
    return None


def is_guest_tool(name: str) -> bool:
    return name in TOOLS


async def run_agent_command(
    application: PackageOperationContext | TenantPackageContext,
    operation: str,
    payload: dict[str, Any],
    on_progress: Progress | None,
) -> dict[str, Any]:
    bridge = HostBridge(application)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(
            [str(_ROOT), *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "plugins.business.agent.guest.stdio",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_ROOT),
        env=env,
        limit=RPC_LINE_LIMIT,
    )
    assert process.stdin is not None
    assert process.stdout is not None
    start = {
        "operation": operation,
        "payload": payload,
        "user_id": bridge.user_id,
        "tenant_id": bridge.tenant_id,
        "project_id": bridge.project_id,
    }
    process.stdin.write(json.dumps(start, separators=(",", ":")).encode() + b"\n")
    await process.stdin.drain()
    result: dict[str, Any] | None = None
    try:
        while True:
            line = await asyncio.wait_for(process.stdout.readline(), 60)
            if not line:
                break
            message = json.loads(line)
            kind = message.get("type")
            if kind == "progress" and on_progress is not None:
                await on_progress(message["data"])
            elif kind == "call":
                output, code, text = await _serve(bridge, message, on_progress)
                reply = {"id": message["id"], "ok": code is None, "output": output}
                if code is not None:
                    reply["code"] = code
                    reply["message"] = text
                process.stdin.write(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
                await process.stdin.drain()
            elif kind == "result":
                result = message
                break
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if result is None or not result.get("ok", False):
        code = "runtime_unavailable" if result is None else str(result.get("code"))
        text = "agent command guest failed" if result is None else str(result.get("message"))
        raise OptionalBusinessError(code, text)
    output = result.get("output")
    if not isinstance(output, dict):
        raise OptionalBusinessError("runtime_unavailable", "agent command guest returned no object")
    return output


async def _serve(  # noqa: C901, PLR0912, PLR0915
    bridge: HostBridge, message: dict[str, Any], on_progress: Progress | None
) -> tuple[Any, str | None, str | None]:
    method = message.get("method")
    params = message.get("params") or {}
    output: Any
    try:
        if method == "http":
            output = await bridge.http(
                params["method"],
                params["path"],
                project_route=bool(params.get("project_route")),
                body=params.get("body"),
                query=params.get("query"),
                absolute=bool(params.get("absolute")),
            )
        elif method == "own":
            await bridge.own(params["conversation_id"])
            output = {}
        elif method == "local_ids":
            output = await bridge.local_ids(list(params.get("ids") or []))
        elif method == "meta":
            output = await bridge.meta(params["conversation_id"])
        elif method == "placements":
            output = await bridge.placements(list(params.get("ids") or []))
        elif method == "run_cloud":
            output = await bridge.run_cloud(params["run_id"], params["conversation_id"])
        elif method == "run_conversation":
            output = await bridge.run_conversation(params["run_id"])
        elif method == "run_fields":
            output = await bridge.run_fields(params["run_id"], params["conversation_id"])
        elif method == "device":
            output = await bridge.device(params["op"], params.get("payload") or {})
        elif method == "stream":

            async def forward(frame: dict[str, Any]) -> None:
                if on_progress is not None:
                    await on_progress(frame)

            output = await bridge.stream(params.get("message") or {}, forward)
        elif method == "actor":
            output = await bridge.actor(params["action"])
        elif method == "voice":
            output = await bridge.voice(params["conversation_id"])
        elif method == "welcome":
            output = await bridge.welcome(params.get("complete"))
        elif method == "model_routes":
            output = await bridge.model_routes()
        elif method == "lifecycle_snapshot":
            output = await bridge.lifecycle_snapshot()
        elif method == "templates":
            output = await bridge.templates(int(params.get("limit") or 50))
        elif method == "hitl":
            output = await bridge.hitl(params["conversation_id"], params["request_id"])
        elif method == "attachment_files":
            output = await bridge.attachment_files(
                params["conversation_id"], list(params.get("ids") or [])
            )
        elif method == "attachment":
            output = await bridge.attachment(params.get("payload") or {})
        elif method == "dashboard":
            output = await bridge.dashboard(params["op"], params.get("payload") or {})
        elif method == "tenant_sessions":
            output = await bridge.tenant_sessions(params["op"], params.get("payload") or {})
        else:
            raise OptionalBusinessError("forbidden", "unknown host capability")
    except OptionalBusinessError as exc:
        return None, exc.code, str(exc)
    return output, None, None
