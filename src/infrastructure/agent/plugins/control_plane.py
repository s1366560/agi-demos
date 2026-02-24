"""Unified plugin runtime control-plane service."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from .manager import PluginRuntimeManager, get_plugin_runtime_manager
from .registry import AgentPluginRegistry, PluginDiagnostic, get_plugin_registry


@dataclass(frozen=True)
class PluginControlPlaneResult:
    """Result for one plugin control-plane action."""

    success: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class PluginControlPlaneService:
    """Single control plane for plugin lifecycle and runtime inventory."""

    def __init__(
        self,
        *,
        runtime_manager: PluginRuntimeManager | None = None,
        registry: AgentPluginRegistry | None = None,
        reconcile_channel_runtime: Callable[[], Awaitable[dict[str, int] | None]] | None = None,
    ) -> None:
        self._runtime_manager = runtime_manager or get_plugin_runtime_manager()
        self._registry = registry or get_plugin_registry()
        self._reconcile_channel_runtime = reconcile_channel_runtime

    async def list_runtime_plugins(
        self,
        *,
        tenant_id: str | None = None,
    ) -> tuple[list[dict[str, Any]], list[dict[str, str]], dict[str, list[str]]]:
        """Load runtime plugins enriched with channel adapter ownership."""
        await self._runtime_manager.ensure_loaded()
        plugin_records, diagnostics = self._runtime_manager.list_plugins(tenant_id=tenant_id)
        channel_factories = self._registry.list_channel_adapter_factories()

        channel_types_by_plugin: dict[str, list[str]] = {}
        for channel_type, (plugin_name, _factory) in channel_factories.items():
            channel_types_by_plugin.setdefault(plugin_name, []).append(channel_type)

        for plugin_name, channel_types in channel_types_by_plugin.items():
            channel_types_by_plugin[plugin_name] = sorted(set(channel_types))

        for record in plugin_records:
            record["channel_types"] = channel_types_by_plugin.get(record["name"], [])

        return (
            plugin_records,
            self._serialize_diagnostics(diagnostics),
            channel_types_by_plugin,
        )

    async def install_plugin(self, requirement: str) -> PluginControlPlaneResult:
        """Install plugin package and reconcile channel runtime."""
        action_trace = self._build_action_trace(action="install", requirement=requirement)
        result = await self._runtime_manager.install_plugin(requirement)
        if not result.get("success"):
            details = dict(result)
            details["control_plane_trace"] = action_trace
            return PluginControlPlaneResult(
                success=False,
                message=str(result.get("error") or "Plugin install failed"),
                details=details,
            )

        details = dict(result)
        details["control_plane_trace"] = action_trace
        await self._attach_channel_runtime_reconcile(details)
        return PluginControlPlaneResult(
            success=True,
            message=f"Installed plugin requirement: {requirement}",
            details=details,
        )

    async def set_plugin_enabled(
        self,
        plugin_name: str,
        *,
        enabled: bool,
        tenant_id: str | None = None,
    ) -> PluginControlPlaneResult:
        """Enable or disable plugin and reconcile channel runtime."""
        action = "enable" if enabled else "disable"
        action_trace = self._build_action_trace(
            action=action,
            plugin_name=plugin_name,
            tenant_id=tenant_id,
        )
        diagnostics = await self._runtime_manager.set_plugin_enabled(
            plugin_name,
            enabled=enabled,
            tenant_id=tenant_id,
        )
        details: dict[str, Any] = {
            "diagnostics": self._serialize_diagnostics(diagnostics),
            "control_plane_trace": action_trace,
        }
        await self._attach_channel_runtime_reconcile(details)
        return PluginControlPlaneResult(
            success=True,
            message=f"{'Enabled' if enabled else 'Disabled'} plugin: {plugin_name}",
            details=details,
        )

    async def uninstall_plugin(self, plugin_name: str) -> PluginControlPlaneResult:
        """Uninstall plugin package and reconcile channel runtime."""
        action_trace = self._build_action_trace(action="uninstall", plugin_name=plugin_name)
        result = await self._runtime_manager.uninstall_plugin(plugin_name)
        details = dict(result)
        details["control_plane_trace"] = action_trace
        if not result.get("success"):
            return PluginControlPlaneResult(
                success=False,
                message=str(result.get("error") or "Plugin uninstall failed"),
                details=details,
            )

        await self._attach_channel_runtime_reconcile(details)
        return PluginControlPlaneResult(
            success=True,
            message=f"Uninstalled plugin: {plugin_name}",
            details=details,
        )

    async def reload_plugins(self) -> PluginControlPlaneResult:
        """Reload plugin runtime and reconcile channel runtime."""
        action_trace = self._build_action_trace(action="reload")
        diagnostics = await self._runtime_manager.reload()
        details: dict[str, Any] = {
            "diagnostics": self._serialize_diagnostics(diagnostics),
            "control_plane_trace": action_trace,
        }
        await self._attach_channel_runtime_reconcile(details)
        return PluginControlPlaneResult(
            success=True,
            message="Plugin runtime reloaded",
            details=details,
        )

    async def _attach_channel_runtime_reconcile(self, details: dict[str, Any]) -> None:
        if self._reconcile_channel_runtime is None:
            return
        channel_reload_plan = await self._reconcile_channel_runtime()
        if channel_reload_plan is not None:
            details["channel_reload_plan"] = channel_reload_plan

    def _build_action_trace(
        self,
        *,
        action: str,
        plugin_name: str | None = None,
        requirement: str | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        return {
            "trace_id": f"plugin-control-plane:{uuid4().hex}",
            "action": action,
            "plugin_name": plugin_name,
            "requirement": requirement,
            "tenant_id": tenant_id,
            "timestamp": datetime.now(UTC).isoformat(),
            "capability_counts": {
                "channel_types": len(self._registry.list_channel_type_metadata()),
                "tool_factories": len(self._registry.list_tool_factories()),
                "hooks": len(self._registry.list_hooks()),
                "commands": len(self._registry.list_commands()),
                "services": len(self._registry.list_services()),
                "providers": len(self._registry.list_providers()),
            },
        }

    @staticmethod
    def _serialize_diagnostics(diagnostics: list[PluginDiagnostic]) -> list[dict[str, str]]:
        return [
            {
                "plugin_name": diagnostic.plugin_name,
                "code": diagnostic.code,
                "message": diagnostic.message,
                "level": diagnostic.level,
            }
            for diagnostic in diagnostics
        ]
