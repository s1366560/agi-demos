"""Subprocess runtime boundary for untrusted tool plugins (I5).

Each call spawns a fresh child process — a crash, hang, or runaway output
never touches the host process. The child speaks one JSON-RPC request over
stdin and answers on stdout; quota accounting (concurrency, output bytes,
wall time) flows through :class:`ResourceQuotaEnforcer`, and audit events
go to the ``plugin_audit`` logger unless an audit callback is supplied.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from .governance import ResourceQuotaEnforcer

logger = logging.getLogger("plugin_audit")

__all__ = [
    "DEFAULT_MAX_OUTPUT_BYTES",
    "DEFAULT_TIMEOUT_SECONDS",
    "SubprocessHostError",
    "SubprocessToolHost",
]

DEFAULT_TIMEOUT_SECONDS = 5.0
DEFAULT_MAX_OUTPUT_BYTES = 65_536


class SubprocessHostError(RuntimeError):
    """Raised for spawn, protocol, timeout, or crash failures."""


@dataclass(frozen=True)
class SubprocessCallOutcome:
    """One measured subprocess tool invocation."""

    plugin_id: str
    tool_id: str
    result: object
    wall_time_ms: int


class SubprocessToolHost:
    """Invoke one tool plugin behind a subprocess + JSON-RPC boundary."""

    def __init__(
        self,
        plugin_id: str,
        command: Sequence[str],
        *,
        quota_enforcer: ResourceQuotaEnforcer | None = None,
        audit: Callable[[Mapping[str, object]], None] | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
        tenant_id: str = "default",
    ) -> None:
        if not plugin_id.strip():
            raise SubprocessHostError("plugin_id must be non-empty")
        if not command:
            raise SubprocessHostError("command must be non-empty")
        self._plugin_id = plugin_id
        self._command = tuple(command)
        self._quota = quota_enforcer
        self._audit = audit or self._log_audit
        self._timeout = timeout_seconds
        self._max_output = max_output_bytes
        self._tenant_id = tenant_id

    async def call(self, tool_id: str, input_json: str) -> SubprocessCallOutcome:
        """Run one tool call in a fresh child process."""
        if not tool_id.strip():
            raise SubprocessHostError("tool_id must be non-empty")
        acquired = False
        started = time.monotonic()
        outcome: SubprocessCallOutcome | None = None
        error: str | None = None
        try:
            if self._quota is not None:
                self._quota.acquire(self._plugin_id, network_requests=1)
                acquired = True
            result = await self._invoke(tool_id, input_json)
            wall_ms = int((time.monotonic() - started) * 1000)
            outcome = SubprocessCallOutcome(
                plugin_id=self._plugin_id,
                tool_id=tool_id,
                result=result,
                wall_time_ms=wall_ms,
            )
            return outcome
        except SubprocessHostError as exc:
            error = str(exc)
            raise
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            wall_ms = int((time.monotonic() - started) * 1000)
            if self._quota is not None and acquired:
                self._quota.release(self._plugin_id, wall_time_ms=wall_ms)
            self._audit(
                {
                    "event": "subprocess_tool_call",
                    "plugin_id": self._plugin_id,
                    "tenant_id": self._tenant_id,
                    "tool_id": tool_id,
                    "wall_time_ms": wall_ms,
                    "result": "ok" if outcome is not None else "error",
                    **({"error": error} if error is not None else {}),
                }
            )

    async def _invoke(self, tool_id: str, input_json: str) -> object:
        request = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tool.call",
                "params": {"tool": tool_id, "input": input_json},
            }
        )
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=self._max_output,
            )
        except OSError as exc:
            raise SubprocessHostError(f"cannot spawn {self._command[0]}: {exc}") from exc
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(request.encode("utf-8")),
                timeout=self._timeout,
            )
        except TimeoutError as exc:
            _ = process.kill()
            _ = await process.wait()
            raise SubprocessHostError(
                f"subprocess tool call timed out after {self._timeout}s"
            ) from exc
        if process.returncode != 0:
            stderr_text = stderr.decode("utf-8", errors="replace")[:500]
            raise SubprocessHostError(f"subprocess exited with {process.returncode}: {stderr_text}")
        if len(stdout) > self._max_output:
            raise SubprocessHostError("subprocess output exceeds the byte budget")
        try:
            response = json.loads(stdout.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SubprocessHostError(f"invalid JSON-RPC response: {exc}") from exc
        if not isinstance(response, dict) or "error" in response:
            raise SubprocessHostError(f"subprocess tool error: {response.get('error')}")
        return response.get("result")

    @staticmethod
    def _log_audit(event: Mapping[str, object]) -> None:
        logger.info("%s", json.dumps(dict(event), sort_keys=True))
