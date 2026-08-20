"""WASM host for untrusted tool plugins (I5).

Contract alignment with the Rust `adapters-wasmtime` crate: the module
exports ``score(i32) -> i32`` and receives the input byte length. Every
invocation gets a fresh store — fuel budgets are per-call and no state
leaks between calls — and quota accounting (concurrency, fuel, wall
time) flows through :class:`ResourceQuotaEnforcer`. Audit events go to
the ``plugin_audit`` logger unless an audit callback is supplied.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
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
    ) -> None:
        if not plugin_id.strip():
            raise WasmHostError("plugin_id must be non-empty")
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
            self._engine = wasmtime.Engine(config)
            self._module = wasmtime.Module(self._engine, module_bytes)
        except wasmtime.WasmtimeError as exc:
            raise WasmHostError(f"invalid wasm artifact for {plugin_id}: {exc}") from exc
        exports = {export.name for export in self._module.exports}
        if "score" not in exports:
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

    def call(self, tool_id: str, input_json: str) -> WasmCallOutcome:
        """Invoke the exported ``score`` with fuel + quota accounting."""
        if not tool_id.strip():
            raise WasmHostError("tool_id must be non-empty")
        input_bytes = len(input_json.encode("utf-8"))
        acquired = False
        started = time.monotonic()
        outcome: WasmCallOutcome | None = None
        error: str | None = None
        try:
            if self._quota is not None:
                self._quota.acquire(
                    self._plugin_id,
                    wasm_fuel=self._fuel_budget,
                    network_requests=1,
                )
                acquired = True
            store = self._wasmtime.Store(self._engine)
            try:
                store.set_fuel(self._fuel_budget)
            except self._wasmtime.WasmtimeError as exc:
                raise WasmHostError(f"cannot budget fuel: {exc}") from exc
            instance = self._wasmtime.Instance(store, self._module, [])
            score_export = instance.exports(store)["score"]
            score = cast(Callable[[object, int], object], score_export)(store, input_bytes)
            if not isinstance(score, int):
                raise WasmHostError("score export returned a non-i32 value")
            remaining = store.get_fuel()
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
            wall_ms = int((time.monotonic() - started) * 1000)
            if self._quota is not None and acquired:
                self._quota.release(self._plugin_id, wall_time_ms=wall_ms)
            self._audit(
                {
                    "event": "wasm_tool_call",
                    "plugin_id": self._plugin_id,
                    "tenant_id": self._tenant_id,
                    "tool_id": tool_id,
                    "wall_time_ms": wall_ms,
                    "result": "ok" if outcome is not None else "error",
                    **({"score": outcome.score} if outcome is not None else {}),
                    **({"error": error} if error is not None else {}),
                }
            )

    @staticmethod
    def _log_audit(event: Mapping[str, object]) -> None:
        logger.info("%s", json.dumps(dict(event), sort_keys=True))
