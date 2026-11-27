"""Run one business command in a child process that cannot see the caller token."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import HTTPException

from plugins.business.automation.guest.dispatch import TOOLS as AUTOMATION_TOOLS
from plugins.business.billing.guest.dispatch import TOOLS as BILLING_TOOLS
from plugins.business.environments.guest.dispatch import TOOLS as ENVIRONMENT_TOOLS
from plugins.business.guest_runtime.binding import RPC_LINE_LIMIT
from plugins.business.knowledge.guest.dispatch import TOOLS as KNOWLEDGE_TOOLS
from plugins.business.workspace.guest.dispatch import TOOLS as WORKSPACE_TOOLS
from src.host.operations.application_commands import PackageOperationContext
from src.host.operations.business_guest.bridge import HostBridge
from src.host.operations.business_guest.capabilities import CAPABILITIES
from src.host.operations.tenant_commands import TenantPackageContext
from src.infrastructure.plugins.v2.signed_optional_business_v2 import OptionalBusinessError

type Progress = Callable[[dict[str, Any]], Awaitable[None]]

_ROOT = Path(__file__).resolve().parents[4]
_TOOLS = {
    "memstack-workspace": WORKSPACE_TOOLS,
    "memstack-knowledge": KNOWLEDGE_TOOLS,
    "memstack-automation": AUTOMATION_TOOLS,
    "memstack-environments": ENVIRONMENT_TOOLS,
    "memstack-billing": BILLING_TOOLS,
}
_MODULES = {
    "memstack-workspace": "plugins.business.workspace.guest.stdio",
    "memstack-knowledge": "plugins.business.knowledge.guest.stdio",
    "memstack-automation": "plugins.business.automation.guest.stdio",
    "memstack-environments": "plugins.business.environments.guest.stdio",
    "memstack-billing": "plugins.business.billing.guest.stdio",
}


class _Command(Protocol):
    tool: str
    host_operation: str | None


def guest_operation(plugin_id: str, command: _Command) -> str | None:
    """Return the operation when this command must leave the host process."""
    table = _TOOLS.get(plugin_id)
    if table is None:
        return None
    if command.tool in table:
        return table[command.tool]
    operation = command.host_operation
    if operation is not None and operation in CAPABILITIES and operation in set(table.values()):
        return operation
    return None


def is_business_guest_tool(name: str) -> bool:
    return any(name in table for table in _TOOLS.values())


def runs_outside_process(name: str) -> bool:
    return name in CAPABILITIES


def subprocess_env() -> dict[str, str]:
    """Environment for the guest. Secrets and the database URL are not copied."""
    return {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONPATH": os.pathsep.join(
            [str(_ROOT), *os.environ.get("PYTHONPATH", "").split(os.pathsep)]
        ),
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "LANG": os.environ.get("LANG", "C.UTF-8"),
    }


async def _read_guest(
    process: asyncio.subprocess.Process,
    bridge: HostBridge,
    on_progress: Progress | None,
) -> dict[str, Any] | None:
    messages: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def pump_stdout() -> None:
        assert process.stdout is not None
        while True:
            line = await process.stdout.readline()
            if not line:
                await messages.put(None)
                return
            await messages.put(json.loads(line))

    pumping = asyncio.create_task(pump_stdout())
    result: dict[str, Any] | None = None
    try:
        while True:
            message = await asyncio.wait_for(messages.get(), 60)
            if message is None:
                break
            kind = message.get("type")
            if kind == "progress" and on_progress is not None:
                await on_progress(message["data"])
            elif kind == "call":
                await _reply(process, bridge, message)
            elif kind == "result":
                result = message
                break
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
        pumping.cancel()
        if result is None and process.stderr is not None:
            error = await process.stderr.read()
            if error:
                result = {
                    "ok": False,
                    "code": "runtime_unavailable",
                    "message": error.decode(errors="replace")[-2000:],
                }
    return result


async def _reply(
    process: asyncio.subprocess.Process, bridge: HostBridge, message: dict[str, Any]
) -> None:
    call_id = message["id"]

    async def relay(frame: dict[str, Any], reply_id: object = call_id) -> None:
        assert process.stdin is not None
        process.stdin.write(
            json.dumps(
                {"type": "event", "id": reply_id, "data": frame}, separators=(",", ":")
            ).encode()
            + b"\n"
        )
        await process.stdin.drain()

    output, code, text = await _serve(bridge, message, relay)
    reply: dict[str, Any] = {"id": call_id, "ok": code is None, "output": output}
    if code is not None:
        reply["code"] = code
        reply["message"] = text
    assert process.stdin is not None
    process.stdin.write(json.dumps(reply, separators=(",", ":")).encode() + b"\n")
    await process.stdin.drain()


async def run_business_command(
    application: PackageOperationContext | TenantPackageContext,
    plugin_id: str,
    operation: str,
    payload: dict[str, Any],
    on_progress: Progress | None,
) -> dict[str, Any]:
    module = _MODULES.get(plugin_id)
    if module is None or operation not in CAPABILITIES:
        raise OptionalBusinessError("forbidden", "unknown business command")
    bridge = HostBridge(application)
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        module,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(_ROOT),
        env=subprocess_env(),
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
    result = await _read_guest(process, bridge, on_progress)

    if result is None or not result.get("ok", False):
        code = "runtime_unavailable" if result is None else str(result.get("code"))
        text = "business command guest failed" if result is None else str(result.get("message"))
        raise OptionalBusinessError(code, text)
    output = result.get("output")
    if not isinstance(output, dict):
        raise OptionalBusinessError(
            "runtime_unavailable", "business command guest returned no object"
        )
    return output


async def _serve(
    bridge: HostBridge, message: dict[str, Any], on_progress: Progress | None
) -> tuple[Any, str | None, str | None]:
    method = message.get("method")
    params = message.get("params") or {}
    try:
        if method == "data":
            output: Any = await bridge.data(
                str(params.get("name") or ""), params.get("params") or {}, on_progress
            )
        elif method == "http":
            output = await bridge.http(
                str(params.get("method") or "GET"),
                str(params.get("path") or ""),
                body=params.get("body"),
                query=params.get("query"),
                headers=params.get("headers"),
            )
        else:
            raise OptionalBusinessError("forbidden", "unknown host capability")
    except OptionalBusinessError as exc:
        return None, exc.code, str(exc)
    except HTTPException as exc:
        code = {401: "forbidden", 403: "forbidden", 404: "page_not_found", 409: "conflict"}.get(
            exc.status_code, "runtime_unavailable"
        )
        return None, code, str(exc.detail)
    except Exception as exc:
        return None, "runtime_unavailable", str(exc)
    return output, None, None
