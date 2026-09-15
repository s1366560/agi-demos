"""WASM host for untrusted tool plugins (I5).

Contract alignment with the Rust `adapters-wasmtime` crate: the module
exports ``score(i32) -> i32`` and receives the input byte length. Every
invocation gets a fresh store — fuel budgets are per-call and no state
leaks between calls — and quota accounting (concurrency, fuel, wall
time) flows through :class:`ResourceQuotaEnforcer`. Audit events go to
the ``plugin_audit`` logger unless an audit callback is supplied.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Lock, Timer
from typing import cast

from .governance import ResourceQuotaEnforcer

logger = logging.getLogger("plugin_audit")

__all__ = [
    "DEFAULT_FUEL_BUDGET",
    "WasmCallOutcome",
    "WasmHostError",
    "WasmToolHost",
]

#: Deterministic per-instruction budget (mirrors the Rust default).
DEFAULT_FUEL_BUDGET = 1_000_000_000
DEFAULT_MEMORY_LIMIT_BYTES = 64 * 1024 * 1024
DEFAULT_WALL_TIME_MS = 5_000


class WasmHostError(RuntimeError):
    """Raised for artifact, contract, or execution failures in the WASM host."""


@dataclass(frozen=True)
class WasmCallOutcome:
    """One measured tool invocation."""

    plugin_id: str
    tool_id: str
    score: int
    input_bytes: int
    fuel_consumed: int
    wall_time_ms: int


class WasmToolHost:
    """Serve PlainCapability(Tool) calls from one verified wasm artifact."""

    def __init__(
        self,
        plugin_id: str,
        module_bytes: bytes,
        *,
        quota_enforcer: ResourceQuotaEnforcer | None = None,
        audit: Callable[[Mapping[str, object]], None] | None = None,
        fuel_budget: int = DEFAULT_FUEL_BUDGET,
        tenant_id: str = "default",
        memory_limit_bytes: int = DEFAULT_MEMORY_LIMIT_BYTES,
        wall_time_ms: int = DEFAULT_WALL_TIME_MS,
    ) -> None:
        if not plugin_id.strip():
            raise WasmHostError("plugin_id must be non-empty")
        for name, value in (
            ("fuel", fuel_budget),
            ("memory", memory_limit_bytes),
            ("wall time", wall_time_ms),
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise WasmHostError(f"{name} budget must be a positive integer")
        self._memory_limit = memory_limit_bytes
        self._wall_time_ms = wall_time_ms
        self._call_lock = Lock()
        self._closed = False
        self._plugin_id = plugin_id
        self._quota = quota_enforcer
        self._audit = audit or self._log_audit
        self._fuel_budget = fuel_budget
        self._tenant_id = tenant_id
        try:
            import wasmtime
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise WasmHostError("wasmtime package is required for the WASM host") from exc
        self._wasmtime = wasmtime
        try:
            config = wasmtime.Config()
            config.consume_fuel = True
            config.epoch_interruption = True
            config.wasm_threads = False
            config.wasm_memory64 = False
            config.wasm_multi_memory = False
            config.max_wasm_stack = 512 * 1024
            self._engine = wasmtime.Engine(config)
            self._module = wasmtime.Module(self._engine, module_bytes)
        except wasmtime.WasmtimeError as exc:
            raise WasmHostError(f"invalid wasm artifact for {plugin_id}: {exc}") from exc
        if self._module.imports:
            raise WasmHostError("wasm score modules cannot import functions, memory, or WASI")
        exports = {export.name: export.type for export in self._module.exports}
        score_type = exports.get("score")
        if not (
            isinstance(score_type, wasmtime.FuncType)
            and [str(value) for value in score_type.params] == ["i32"]
            and [str(value) for value in score_type.results] == ["i32"]
        ):
            raise WasmHostError(f"wasm artifact for {plugin_id} must export score(i32) -> i32")

    @classmethod
    def from_path(
        cls,
        plugin_id: str,
        path: Path,
        *,
        expected_sha256: str | None = None,
        **kwargs: object,
    ) -> WasmToolHost:
        """Load an artifact from disk, verifying its digest when supplied."""
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise WasmHostError(f"cannot read wasm artifact {path}: {exc}") from exc
        if expected_sha256 is not None:
            digest = hashlib.sha256(raw).hexdigest()
            if digest != expected_sha256:
                raise WasmHostError(
                    f"wasm artifact digest mismatch for {plugin_id}: "
                    f"expected {expected_sha256}, got {digest}"
                )
        return cls(plugin_id, raw, **kwargs)  # type: ignore[arg-type]

    def call(
        self, tool_id: str, input_json: str, *, tenant_id: str | None = None
    ) -> WasmCallOutcome:
        """Invoke the exported ``score`` with fuel + quota accounting."""
        if not tool_id.strip():
            raise WasmHostError("tool_id must be non-empty")
        input_bytes = len(input_json.encode("utf-8"))
        acquired = False
        locked = False
        started = time.monotonic()
        outcome: WasmCallOutcome | None = None
        error: str | None = None
        try:
            locked = self._call_lock.acquire(timeout=self._wall_time_ms / 1000)
            if not locked or (time.monotonic() - started) * 1000 >= self._wall_time_ms:
                raise WasmHostError("wasm wall-clock deadline exceeded while waiting")
            if self._closed:
                raise WasmHostError("wasm host is closed")
            if input_bytes > 1024 * 1024:
                raise WasmHostError("wasm input exceeds the byte budget")
            if self._quota is not None:
                self._quota.acquire(
                    self._plugin_id,
                    wasm_fuel=self._fuel_budget,
                    wasm_memory_bytes=self._memory_limit,
                    wall_time_ms=self._wall_time_ms,
                    network_requests=0,
                )
                acquired = True
            score, remaining = self._invoke(input_bytes, started)
            wall_ms = int((time.monotonic() - started) * 1000)
            outcome = WasmCallOutcome(
                plugin_id=self._plugin_id,
                tool_id=tool_id,
                score=score,
                input_bytes=input_bytes,
                fuel_consumed=max(0, self._fuel_budget - remaining),
                wall_time_ms=wall_ms,
            )
            return outcome
        except (self._wasmtime.WasmtimeError, self._wasmtime.Trap) as exc:
            error = str(exc)
            raise WasmHostError(f"wasm execution failed for {self._plugin_id}: {exc}") from exc
        except Exception as exc:
            error = str(exc)
            raise
        finally:
            if locked:
                self._call_lock.release()
            wall_ms = int((time.monotonic() - started) * 1000)
            if self._quota is not None and acquired:
                self._quota.release(self._plugin_id, wall_time_ms=wall_ms)
            self._audit(
                {
                    "event": "wasm_tool_call",
                    "plugin_id": self._plugin_id,
                    "tenant_id": tenant_id if tenant_id is not None else self._tenant_id,
                    "tool_id": tool_id,
                    "wall_time_ms": wall_ms,
                    "result": "ok" if outcome is not None else "error",
                    **({"score": outcome.score} if outcome is not None else {}),
                    **({"error": error} if error is not None else {}),
                }
            )

    def _invoke(self, input_bytes: int, started: float) -> tuple[int, int]:
        store = self._wasmtime.Store(self._engine)
        timer: Timer | None = None
        try:
            store.set_limits(
                memory_size=self._memory_limit,
                table_elements=10_000,
                instances=1,
                tables=1,
                memories=1,
            )
            store.set_fuel(self._fuel_budget)
            store.set_epoch_deadline(1)
            remaining_seconds = self._wall_time_ms / 1000 - (time.monotonic() - started)
            if remaining_seconds <= 0:
                raise WasmHostError("wasm wall-clock deadline exceeded")
            timer = Timer(remaining_seconds, self._engine.increment_epoch)
            timer.daemon = True
            timer.start()
            instance = self._wasmtime.Instance(store, self._module, [])
            score = cast(Callable[[object, int], object], instance.exports(store)["score"])(
                store, input_bytes
            )
            if not isinstance(score, int):
                raise WasmHostError("score export returned a non-i32 value")
            if (time.monotonic() - started) * 1000 >= self._wall_time_ms:
                raise WasmHostError("wasm wall-clock deadline exceeded")
            return score, store.get_fuel()
        finally:
            if timer is not None:
                timer.cancel()
                timer.join()
            store.close()

    async def call_async(
        self, tool_id: str, input_json: str, *, tenant_id: str | None = None
    ) -> WasmCallOutcome:
        """Run bounded native Wasmtime work off the asyncio event loop."""
        return await asyncio.to_thread(self.call, tool_id, input_json, tenant_id=tenant_id)

    def close(self) -> None:
        """Finish bounded in-flight work, then deny all future invocations."""
        with self._call_lock:
            if not self._closed:
                self._closed = True
                self._module.close()
                self._engine.close()

    @staticmethod
    def _log_audit(event: Mapping[str, object]) -> None:
        logger.info("%s", json.dumps(dict(event), sort_keys=True))
