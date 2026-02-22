"""Plugin registry for agent runtime extensions."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PluginToolFactory = Callable[
    ["PluginToolBuildContext"], Dict[str, Any] | Awaitable[Dict[str, Any]]
]
ChannelReloadHook = Callable[["ChannelReloadContext"], None | Awaitable[None]]
ChannelAdapterFactory = Callable[["ChannelAdapterBuildContext"], Any | Awaitable[Any]]


@dataclass(frozen=True)
class PluginToolBuildContext:
    """Build context passed to plugin tool factories."""

    tenant_id: str
    project_id: str
    base_tools: Dict[str, Any]


@dataclass(frozen=True)
class ChannelReloadContext:
    """Reload context passed to plugin channel reload hooks."""

    plan_summary: Dict[str, int]
    dry_run: bool


@dataclass(frozen=True)
class ChannelAdapterBuildContext:
    """Build context passed to plugin channel adapter factories."""

    channel_type: str
    config_model: Any
    channel_config: Any


@dataclass(frozen=True)
class ChannelTypeConfigMetadata:
    """Configuration metadata registered for one channel type."""

    plugin_name: str
    channel_type: str
    config_schema: Optional[Dict[str, Any]] = None
    config_ui_hints: Optional[Dict[str, Any]] = None
    defaults: Optional[Dict[str, Any]] = None
    secret_paths: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginDiagnostic:
    """Diagnostic record emitted by plugin runtime operations."""

    plugin_name: str
    code: str
    message: str
    level: str = "warning"


class AgentPluginRegistry:
    """Registry for plugin-provided capabilities."""

    def __init__(self) -> None:
        self._tool_factories: Dict[str, PluginToolFactory] = {}
        self._channel_reload_hooks: Dict[str, ChannelReloadHook] = {}
        self._channel_adapter_factories: Dict[str, tuple[str, ChannelAdapterFactory]] = {}
        self._channel_type_metadata: Dict[str, ChannelTypeConfigMetadata] = {}
        self._lock = RLock()

    def register_tool_factory(
        self,
        plugin_name: str,
        factory: PluginToolFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin tool factory."""
        with self._lock:
            if plugin_name in self._tool_factories and not overwrite:
                raise ValueError(f"Tool factory already registered for plugin: {plugin_name}")
            self._tool_factories[plugin_name] = factory

    def register_channel_reload_hook(
        self,
        plugin_name: str,
        hook: ChannelReloadHook,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin channel reload hook."""
        with self._lock:
            if plugin_name in self._channel_reload_hooks and not overwrite:
                raise ValueError(f"Channel reload hook already registered for plugin: {plugin_name}")
            self._channel_reload_hooks[plugin_name] = hook

    def register_channel_adapter_factory(
        self,
        plugin_name: str,
        channel_type: str,
        factory: ChannelAdapterFactory,
        *,
        config_schema: Optional[Dict[str, Any]] = None,
        config_ui_hints: Optional[Dict[str, Any]] = None,
        defaults: Optional[Dict[str, Any]] = None,
        secret_paths: Optional[List[str]] = None,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin-provided channel adapter factory."""
        normalized_channel_type = (channel_type or "").strip().lower()
        if not normalized_channel_type:
            raise ValueError("channel_type is required")

        with self._lock:
            if normalized_channel_type in self._channel_adapter_factories and not overwrite:
                existing_plugin = self._channel_adapter_factories[normalized_channel_type][0]
                raise ValueError(
                    "Channel adapter factory already registered "
                    f"for channel_type={normalized_channel_type} by plugin={existing_plugin}"
                )
            self._channel_adapter_factories[normalized_channel_type] = (plugin_name, factory)
            self._channel_type_metadata[normalized_channel_type] = ChannelTypeConfigMetadata(
                plugin_name=plugin_name,
                channel_type=normalized_channel_type,
                config_schema=dict(config_schema) if isinstance(config_schema, dict) else None,
                config_ui_hints=dict(config_ui_hints)
                if isinstance(config_ui_hints, dict)
                else None,
                defaults=dict(defaults) if isinstance(defaults, dict) else None,
                secret_paths=list(secret_paths or []),
            )

    def list_tool_factories(self) -> Dict[str, PluginToolFactory]:
        """Return a snapshot of registered tool factories."""
        with self._lock:
            return dict(self._tool_factories)

    def list_channel_adapter_factories(self) -> Dict[str, tuple[str, ChannelAdapterFactory]]:
        """Return a snapshot of channel adapter factories keyed by channel_type."""
        with self._lock:
            return dict(self._channel_adapter_factories)

    def list_channel_type_metadata(self) -> Dict[str, ChannelTypeConfigMetadata]:
        """Return channel configuration metadata keyed by channel_type."""
        with self._lock:
            return dict(self._channel_type_metadata)

    async def build_tools(
        self,
        context: PluginToolBuildContext,
    ) -> tuple[Dict[str, Any], List[PluginDiagnostic]]:
        """Build plugin-provided tools for the given context."""
        tool_factories = self.list_tool_factories()
        diagnostics: List[PluginDiagnostic] = []
        plugin_tools: Dict[str, Any] = {}

        for plugin_name, factory in tool_factories.items():
            try:
                produced = factory(context)
                if inspect.isawaitable(produced):
                    produced = await produced
                if not isinstance(produced, dict):
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="invalid_tool_factory_result",
                            message="Tool factory must return Dict[str, Any]",
                            level="error",
                        )
                    )
                    continue
                for tool_name, tool_impl in produced.items():
                    if tool_name in context.base_tools or tool_name in plugin_tools:
                        diagnostics.append(
                            PluginDiagnostic(
                                plugin_name=plugin_name,
                                code="tool_name_conflict",
                                message=f"Skipped conflicting tool name: {tool_name}",
                            )
                        )
                        continue
                    plugin_tools[tool_name] = tool_impl
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_loaded",
                        message=f"Registered {len(produced)} plugin tool(s)",
                        level="info",
                    )
                )
            except Exception as exc:
                # Plugin failures are isolated by design to avoid taking down tool bootstrap.
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="tool_factory_failed",
                        message=str(exc),
                        level="error",
                    )
                )

        return plugin_tools, diagnostics

    async def notify_channel_reload(
        self,
        *,
        plan_summary: Dict[str, int],
        dry_run: bool,
    ) -> List[PluginDiagnostic]:
        """Notify registered plugins about channel reload planning/execution."""
        with self._lock:
            hooks = dict(self._channel_reload_hooks)

        diagnostics: List[PluginDiagnostic] = []
        context = ChannelReloadContext(plan_summary=dict(plan_summary), dry_run=dry_run)
        for plugin_name, hook in hooks.items():
            try:
                result = hook(context)
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                # Reload hook errors are surfaced via diagnostics but do not block reload flow.
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="channel_reload_hook_failed",
                        message=str(exc),
                        level="error",
                    )
                )
        return diagnostics

    async def build_channel_adapter(
        self,
        context: ChannelAdapterBuildContext,
    ) -> tuple[Any | None, List[PluginDiagnostic]]:
        """Build a channel adapter from plugin factory for the requested channel_type."""
        channel_type = (context.channel_type or "").strip().lower()
        if not channel_type:
            return None, []

        with self._lock:
            factory_entry = self._channel_adapter_factories.get(channel_type)

        if not factory_entry:
            return None, []

        plugin_name, factory = factory_entry
        diagnostics: List[PluginDiagnostic] = []
        try:
            adapter = factory(context)
            if inspect.isawaitable(adapter):
                adapter = await adapter
            if adapter is None:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="invalid_channel_adapter_result",
                        message="Channel adapter factory returned None",
                        level="error",
                    )
                )
                return None, diagnostics
            diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin_name,
                    code="channel_adapter_loaded",
                    message=f"Loaded adapter for channel_type={channel_type}",
                    level="info",
                )
            )
            return adapter, diagnostics
        except Exception as exc:
            diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin_name,
                    code="channel_adapter_factory_failed",
                    message=str(exc),
                    level="error",
                )
            )
            return None, diagnostics

    def clear(self) -> None:
        """Clear registry state (primarily for tests)."""
        with self._lock:
            self._tool_factories.clear()
            self._channel_reload_hooks.clear()
            self._channel_adapter_factories.clear()
            self._channel_type_metadata.clear()


_global_plugin_registry = AgentPluginRegistry()


def get_plugin_registry() -> AgentPluginRegistry:
    """Get the global plugin registry singleton."""
    return _global_plugin_registry
