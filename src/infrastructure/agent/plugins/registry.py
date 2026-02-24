"""Plugin registry for agent runtime extensions."""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from threading import RLock
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional

logger = logging.getLogger(__name__)

PluginToolFactory = Callable[["PluginToolBuildContext"], Dict[str, Any] | Awaitable[Dict[str, Any]]]
ChannelReloadHook = Callable[["ChannelReloadContext"], None | Awaitable[None]]
ChannelAdapterFactory = Callable[["ChannelAdapterBuildContext"], Any | Awaitable[Any]]
PluginHookHandler = Callable[[Mapping[str, Any]], None | Awaitable[None]]
PluginCommandHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]


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
        self._hook_handlers: Dict[str, Dict[str, PluginHookHandler]] = {}
        self._commands: Dict[str, tuple[str, PluginCommandHandler]] = {}
        self._services: Dict[str, tuple[str, Any]] = {}
        self._providers: Dict[str, tuple[str, Any]] = {}
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
                raise ValueError(
                    f"Channel reload hook already registered for plugin: {plugin_name}"
                )
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

    def register_hook(
        self,
        plugin_name: str,
        hook_name: str,
        handler: PluginHookHandler,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a named runtime hook handler."""
        normalized_hook_name = (hook_name or "").strip().lower()
        if not normalized_hook_name:
            raise ValueError("hook_name is required")
        with self._lock:
            bucket = self._hook_handlers.setdefault(normalized_hook_name, {})
            if plugin_name in bucket and not overwrite:
                raise ValueError(
                    f"Hook already registered for plugin={plugin_name}: {normalized_hook_name}"
                )
            bucket[plugin_name] = handler

    def register_command(
        self,
        plugin_name: str,
        command_name: str,
        handler: PluginCommandHandler,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a command handler scoped by unique command name."""
        normalized_name = (command_name or "").strip().lower()
        if not normalized_name:
            raise ValueError("command_name is required")
        with self._lock:
            if normalized_name in self._commands and not overwrite:
                existing_plugin = self._commands[normalized_name][0]
                raise ValueError(
                    "Command already registered "
                    f"for command={normalized_name} by plugin={existing_plugin}"
                )
            self._commands[normalized_name] = (plugin_name, handler)

    def register_service(
        self,
        plugin_name: str,
        service_name: str,
        service: Any,  # noqa: ANN401
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin service object."""
        normalized_name = (service_name or "").strip().lower()
        if not normalized_name:
            raise ValueError("service_name is required")
        with self._lock:
            if normalized_name in self._services and not overwrite:
                existing_plugin = self._services[normalized_name][0]
                raise ValueError(
                    "Service already registered "
                    f"for service={normalized_name} by plugin={existing_plugin}"
                )
            self._services[normalized_name] = (plugin_name, service)

    def register_provider(
        self,
        plugin_name: str,
        provider_name: str,
        provider: Any,  # noqa: ANN401
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a provider object for runtime lookup."""
        normalized_name = (provider_name or "").strip().lower()
        if not normalized_name:
            raise ValueError("provider_name is required")
        with self._lock:
            if normalized_name in self._providers and not overwrite:
                existing_plugin = self._providers[normalized_name][0]
                raise ValueError(
                    "Provider already registered "
                    f"for provider={normalized_name} by plugin={existing_plugin}"
                )
            self._providers[normalized_name] = (plugin_name, provider)

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

    def list_hooks(self) -> Dict[str, Dict[str, PluginHookHandler]]:
        """Return registered hook handlers grouped by hook name."""
        with self._lock:
            return {
                hook_name: dict(handlers) for hook_name, handlers in self._hook_handlers.items()
            }

    def list_commands(self) -> Dict[str, tuple[str, PluginCommandHandler]]:
        """Return command handlers keyed by command name."""
        with self._lock:
            return dict(self._commands)

    def list_services(self) -> Dict[str, tuple[str, Any]]:
        """Return registered services keyed by service name."""
        with self._lock:
            return dict(self._services)

    def list_providers(self) -> Dict[str, tuple[str, Any]]:
        """Return registered providers keyed by provider name."""
        with self._lock:
            return dict(self._providers)

    async def notify_hook(
        self,
        hook_name: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> List[PluginDiagnostic]:
        """Invoke named hook handlers and collect diagnostics."""
        normalized_name = (hook_name or "").strip().lower()
        if not normalized_name:
            return []

        with self._lock:
            handlers = dict(self._hook_handlers.get(normalized_name, {}))

        diagnostics: List[PluginDiagnostic] = []
        for plugin_name, handler in handlers.items():
            try:
                result = handler(dict(payload or {}))
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="hook_handler_failed",
                        message=f"{normalized_name}: {exc}",
                        level="error",
                    )
                )
        return diagnostics

    async def execute_command(
        self,
        command_name: str,
        *,
        payload: Optional[Mapping[str, Any]] = None,
    ) -> tuple[Any, List[PluginDiagnostic]]:
        """Execute one registered plugin command."""
        normalized_name = (command_name or "").strip().lower()
        if not normalized_name:
            return None, []

        with self._lock:
            command_entry = self._commands.get(normalized_name)
        if not command_entry:
            return None, []

        plugin_name, handler = command_entry
        diagnostics: List[PluginDiagnostic] = []
        try:
            result = handler(dict(payload or {}))
            if inspect.isawaitable(result):
                result = await result
            return result, diagnostics
        except Exception as exc:
            diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin_name,
                    code="command_execution_failed",
                    message=f"{normalized_name}: {exc}",
                    level="error",
                )
            )
            return None, diagnostics

    def get_service(self, service_name: str) -> Any:  # noqa: ANN401
        """Get a service by name if registered."""
        normalized_name = (service_name or "").strip().lower()
        if not normalized_name:
            return None
        with self._lock:
            service_entry = self._services.get(normalized_name)
        if not service_entry:
            return None
        return service_entry[1]

    def get_provider(self, provider_name: str) -> Any:  # noqa: ANN401
        """Get a provider by name if registered."""
        normalized_name = (provider_name or "").strip().lower()
        if not normalized_name:
            return None
        with self._lock:
            provider_entry = self._providers.get(normalized_name)
        if not provider_entry:
            return None
        return provider_entry[1]

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
            self._hook_handlers.clear()
            self._commands.clear()
            self._services.clear()
            self._providers.clear()


_global_plugin_registry = AgentPluginRegistry()


def get_plugin_registry() -> AgentPluginRegistry:
    """Get the global plugin registry singleton."""
    return _global_plugin_registry
