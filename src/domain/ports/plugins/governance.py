"""Plugin permission, trust, and quota contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from src.domain.model.plugins import PluginRuntimeKind, PluginTrust


class PluginPermission(str, Enum):
    """Permissions that can be requested by a plugin manifest."""

    TOOLS_EXECUTE = "tools.execute"
    TOOLS_READ = "tools.read"
    LLM_INVOKE = "llm.invoke"
    CHANNEL_READ = "channel.read"
    CHANNEL_SEND = "channel.send"
    GRAPH_READ = "graph.read"
    GRAPH_WRITE = "graph.write"
    STORAGE_READ = "storage.read"
    STORAGE_WRITE = "storage.write"
    UI_RENDER = "ui.render"
    NETWORK_ACCESS = "network.access"


RUNTIME_PERMISSIONS: dict[PluginRuntimeKind, frozenset[PluginPermission]] = {
    PluginRuntimeKind.WASM: frozenset(
        {PluginPermission.TOOLS_EXECUTE, PluginPermission.TOOLS_READ}
    ),
    PluginRuntimeKind.MCP: frozenset(
        {
            PluginPermission.TOOLS_EXECUTE,
            PluginPermission.TOOLS_READ,
            PluginPermission.NETWORK_ACCESS,
        }
    ),
    PluginRuntimeKind.SUBPROCESS: frozenset(
        {
            PluginPermission.TOOLS_EXECUTE,
            PluginPermission.TOOLS_READ,
            PluginPermission.NETWORK_ACCESS,
        }
    ),
    PluginRuntimeKind.FRONTEND: frozenset({PluginPermission.UI_RENDER}),
    PluginRuntimeKind.PYTHON_TRUSTED: frozenset(set(PluginPermission)),
}


@dataclass(frozen=True)
class ResourceQuota:
    """Per-plugin execution limits."""

    max_wasm_fuel: int | None = None
    max_wasm_memory_bytes: int | None = None
    max_wall_time_ms: int | None = None
    max_concurrent_calls: int | None = None
    max_output_bytes: int | None = None
    max_network_requests_per_minute: int | None = None
    max_storage_bytes: int | None = None
    max_monthly_usd: float | None = None


@dataclass(frozen=True)
class PluginTrustDecision:
    """Deterministic result of runtime/permission gating."""

    allowed: bool
    plugin_id: str
    trust: PluginTrust
    runtime: PluginRuntimeKind
    granted_permissions: frozenset[PluginPermission]
    reason: str
