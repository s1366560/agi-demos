"""Generation-owned telemetry lifecycle with process-shared activation."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .runtime import ContextV2, EffectResultV2, PluginDefinitionV2, generated_contract_digest_v2

TELEMETRY_RUNTIME_MODULE_V2 = "builtin://memstack/telemetry/runtime"
TELEMETRY_RUNTIME_SERVICE_V2 = "service:telemetry.runtime"

type TelemetryStartV2 = Callable[[], bool | Awaitable[bool]]
type TelemetryStopV2 = Callable[[], None | Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class TelemetryRuntimeServiceV2:
    """Telemetry state visible from one immutable generation."""

    initialized: bool
    unavailable_code: str | None = None


@dataclass(kw_only=True)
class TelemetryRuntimeManagerV2:
    """Reference-count one process telemetry runtime across staged generations."""

    start: TelemetryStartV2
    stop: TelemetryStopV2
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False)
    _lease_count: int = field(default=0, init=False)
    _initialized: bool = field(default=False, init=False)

    @property
    def lease_count(self) -> int:
        return self._lease_count

    async def acquire(self) -> bool:
        """Start on the first generation and return the shared initialized state."""
        async with self._lock:
            if self._lease_count == 0:
                result = self.start()
                if inspect.isawaitable(result):
                    result = await result
                self._initialized = result
            self._lease_count += 1
            return self._initialized

    async def release(self) -> None:
        """Stop only after the final overlapping generation is disposed."""
        async with self._lock:
            if self._lease_count == 0:
                return
            self._lease_count -= 1
            if self._lease_count != 0:
                return
            try:
                result = self.stop()
                if inspect.isawaitable(result):
                    await result
            finally:
                self._initialized = False


def telemetry_runtime_definition_v2(
    manager: TelemetryRuntimeManagerV2 | None = None,
) -> PluginDefinitionV2:
    """Bind telemetry startup and shutdown to one V2 Provider effect."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "process-shared":
            raise ValueError("telemetry runtime requires strategy process-shared")

        if manager is None:
            _ = context.provide(
                TELEMETRY_RUNTIME_SERVICE_V2,
                TelemetryRuntimeServiceV2(
                    initialized=False,
                    unavailable_code="telemetry_runtime_manager_unavailable",
                ),
                label="telemetry-runtime",
            )
            return None

        runtime_manager = manager
        initialized = False

        async def acquire() -> TelemetryStopV2:
            nonlocal initialized
            initialized = await runtime_manager.acquire()
            return runtime_manager.release

        await context.effect(acquire, label="telemetry-runtime-lifecycle")
        _ = context.provide(
            TELEMETRY_RUNTIME_SERVICE_V2,
            TelemetryRuntimeServiceV2(initialized=initialized),
            label="telemetry-runtime",
        )
        return None

    return PluginDefinitionV2(
        module_ref=TELEMETRY_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(TELEMETRY_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "TELEMETRY_RUNTIME_MODULE_V2",
    "TELEMETRY_RUNTIME_SERVICE_V2",
    "TelemetryRuntimeManagerV2",
    "TelemetryRuntimeServiceV2",
    "TelemetryStartV2",
    "TelemetryStopV2",
    "telemetry_runtime_definition_v2",
]
