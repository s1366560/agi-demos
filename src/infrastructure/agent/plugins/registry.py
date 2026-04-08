"""Plugin registry for agent runtime extensions."""

from __future__ import annotations

import contextlib
import inspect
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from threading import RLock
from typing import Any

import jsonschema

from src.infrastructure.agent.tools.define import ToolInfo

logger = logging.getLogger(__name__)

PluginToolFactory = Callable[["PluginToolBuildContext"], dict[str, Any] | Awaitable[dict[str, Any]]]
ChannelReloadHook = Callable[["ChannelReloadContext"], None | Awaitable[None]]
ChannelAdapterFactory = Callable[["ChannelAdapterBuildContext"], Any | Awaitable[Any]]
PluginHookHandler = Callable[
    [Mapping[str, Any]],
    Mapping[str, Any] | None | Awaitable[Mapping[str, Any] | None],
]

# Well-known hook names recognised by the agent runtime.
# Plugins may register handlers for any string, but these names have
# documented semantics and are invoked by the core pipeline.
WELL_KNOWN_HOOKS: frozenset[str] = frozenset(
    {
        "before_tool_selection",
        "after_tool_selection",
        "before_tool_execution",
        "after_tool_execution",
        "before_response",
        "after_response",
        "before_planning",
        "after_planning",
        "on_error",
        "on_session_start",
        "on_session_end",
        "on_context_overflow",
        # Sub-agent lifecycle hooks (P1-C)
        "before_subagent_spawn",
        "after_subagent_spawn",
        "before_subagent_complete",
        "after_subagent_complete",
        "on_subagent_doom_loop",
        "on_subagent_routed",
    }
)
PluginCommandHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]
PluginSkillFactory = Callable[
    ["PluginSkillBuildContext"], list[dict[str, Any]] | Awaitable[list[dict[str, Any]]]
]
PluginHttpHandler = Callable[..., Any | Awaitable[Any]]
PluginCliHandler = Callable[[Mapping[str, Any]], Any | Awaitable[Any]]
PluginLifecycleHandler = Callable[[], None | Awaitable[None]]

# Sub-agent resolver plugin extension types.
# A resolver factory receives a build context and returns a ``Resolver`` (or
# an awaitable that resolves to one).  Plugins register these factories via
# ``PluginRuntimeApi.register_subagent_resolver_factory()``.
SubAgentResolverFactory = Callable[
    ["SubAgentResolverBuildContext"], Any | Awaitable[Any]
]

LIFECYCLE_EVENTS: frozenset[str] = frozenset(
    {
        "on_load",
        "on_enable",
        "on_disable",
        "on_unload",
    }
)


@dataclass(frozen=True)
class PluginToolBuildContext:
    """Build context passed to plugin tool factories."""

    tenant_id: str
    project_id: str
    base_tools: dict[str, Any]


@dataclass(frozen=True)
class PluginSkillBuildContext:
    """Build context passed to plugin skill factories."""

    tenant_id: str
    project_id: str
    agent_mode: str


@dataclass(frozen=True)
class ChannelReloadContext:
    """Reload context passed to plugin channel reload hooks."""

    plan_summary: dict[str, int]
    dry_run: bool


@dataclass(frozen=True)
class ChannelAdapterBuildContext:
    """Build context passed to plugin channel adapter factories."""

    channel_type: str
    config_model: Any
    channel_config: Any


@dataclass(frozen=True)
class SubAgentResolverBuildContext:
    """Build context passed to sub-agent resolver factories.

    Plugins receive this when their resolver factory is invoked during
    ``SubAgentRouter`` initialisation so they can configure resolvers
    based on the active project / tenant.
    """

    tenant_id: str
    project_id: str

@dataclass(frozen=True)
class ChannelTypeConfigMetadata:
    """Configuration metadata registered for one channel type."""

    plugin_name: str
    channel_type: str
    config_schema: dict[str, Any] | None = None
    config_ui_hints: dict[str, Any] | None = None
    defaults: dict[str, Any] | None = None
    secret_paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginHttpRoute:
    """Metadata for one HTTP route registered by a plugin."""

    plugin_name: str
    method: str
    path: str
    handler: PluginHttpHandler
    summary: str | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PluginCliCommand:
    """Metadata for one CLI command registered by a plugin."""

    plugin_name: str
    name: str
    handler: PluginCliHandler
    description: str | None = None
    args_schema: dict[str, Any] | None = None


@dataclass(frozen=True)
class PluginConfigSchema:
    """Validated config schema registered by a plugin."""

    plugin_name: str
    schema: dict[str, Any]


@dataclass(frozen=True)
class PluginDiagnostic:
    """Diagnostic record emitted by plugin runtime operations."""

    plugin_name: str
    code: str
    message: str
    level: str = "warning"


@dataclass(frozen=True)
class RegisteredHookMetadata:
    """Catalog metadata for a registered plugin hook."""

    plugin_name: str
    hook_name: str
    display_name: str
    description: str | None = None
    default_priority: int = 100
    default_enabled: bool = True
    default_settings: dict[str, Any] = field(default_factory=dict)
    settings_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDispatchResult:
    """Hook execution result including the final payload and diagnostics."""

    payload: dict[str, Any]
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)


class AgentPluginRegistry:
    """Registry for plugin-provided capabilities."""

    def __init__(self) -> None:
        self._tool_factories: dict[str, PluginToolFactory] = {}
        self._skill_factories: dict[str, PluginSkillFactory] = {}
        self._channel_reload_hooks: dict[str, ChannelReloadHook] = {}
        self._channel_adapter_factories: dict[str, tuple[str, ChannelAdapterFactory]] = {}
        self._channel_type_metadata: dict[str, ChannelTypeConfigMetadata] = {}
        self._hook_handlers: dict[str, dict[str, tuple[int, PluginHookHandler]]] = {}
        self._hook_metadata: dict[tuple[str, str], RegisteredHookMetadata] = {}
        self._commands: dict[str, tuple[str, PluginCommandHandler]] = {}
        self._services: dict[str, tuple[str, Any]] = {}
        self._providers: dict[str, tuple[str, Any]] = {}
        self._http_routes: dict[str, list[PluginHttpRoute]] = {}
        self._cli_commands: dict[str, list[PluginCliCommand]] = {}
        self._lifecycle_hooks: dict[str, dict[str, PluginLifecycleHandler]] = {}
        self._lock = RLock()
        self._lock = RLock()
        self._config_schemas: dict[str, PluginConfigSchema] = {}
        self._sandbox_tool_factories: dict[str, list[PluginToolFactory]] = {}
        self._subagent_resolver_factories: dict[str, SubAgentResolverFactory] = {}

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

    def register_sandbox_tool_factory(
        self,
        plugin_name: str,
        factory: PluginToolFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a sandbox tool factory for a plugin.

        Unlike regular tool factories which are keyed by plugin name (one per plugin),
        sandbox tool factories allow multiple registrations per plugin since a plugin
        may declare several sandbox-side tools.

        When *overwrite* is True, all existing factories for *plugin_name* are replaced.
        """
        with self._lock:
            if overwrite:
                self._sandbox_tool_factories[plugin_name] = [factory]
            else:
                self._sandbox_tool_factories.setdefault(plugin_name, []).append(factory)
    def register_skill_factory(
        self,
        plugin_name: str,
        factory: PluginSkillFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin skill factory."""
        with self._lock:
            if plugin_name in self._skill_factories and not overwrite:
                raise ValueError(f"Skill factory already registered for plugin: {plugin_name}")
            self._skill_factories[plugin_name] = factory

    def register_http_route(
        self,
        plugin_name: str,
        method: str,
        path: str,
        handler: PluginHttpHandler,
        *,
        summary: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register an HTTP route for a plugin."""
        normalized_method = (method or "").strip().upper()
        normalized_path = (path or "").strip()
        if not normalized_method:
            raise ValueError("method is required")
        if not normalized_path:
            raise ValueError("path is required")
        route = PluginHttpRoute(
            plugin_name=plugin_name,
            method=normalized_method,
            path=normalized_path,
            handler=handler,
            summary=summary,
            tags=list(tags or []),
        )
        with self._lock:
            existing = self._http_routes.setdefault(plugin_name, [])
            for existing_route in existing:
                if (
                    existing_route.method == normalized_method
                    and existing_route.path == normalized_path
                ):
                    raise ValueError(
                        f"HTTP route already registered for plugin={plugin_name}: "
                        f"{normalized_method} {normalized_path}"
                    )
            existing.append(route)

    def register_cli_command(
        self,
        plugin_name: str,
        name: str,
        handler: PluginCliHandler,
        *,
        description: str | None = None,
        args_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a CLI command for a plugin."""
        normalized_name = (name or "").strip().lower()
        if not normalized_name:
            raise ValueError("name is required")
        command = PluginCliCommand(
            plugin_name=plugin_name,
            name=normalized_name,
            handler=handler,
            description=description,
            args_schema=dict(args_schema) if isinstance(args_schema, dict) else None,
        )
        with self._lock:
            existing = self._cli_commands.setdefault(plugin_name, [])
            for existing_cmd in existing:
                if existing_cmd.name == normalized_name:
                    raise ValueError(
                        f"CLI command already registered for plugin={plugin_name}: {normalized_name}"
                    )
            existing.append(command)

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
        config_schema: dict[str, Any] | None = None,
        config_ui_hints: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        secret_paths: list[str] | None = None,
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
        priority: int = 100,
        display_name: str | None = None,
        description: str | None = None,
        default_enabled: bool = True,
        default_settings: dict[str, Any] | None = None,
        settings_schema: dict[str, Any] | None = None,
        overwrite: bool = False,
    ) -> None:
        """Register a named runtime hook handler.

        Args:
            plugin_name: Owning plugin identifier.
            hook_name: Hook point name (see ``WELL_KNOWN_HOOKS`` for documented names).
            handler: Async or sync callable invoked when the hook fires.
            priority: Numeric priority -- lower values run first.  Default ``100``.
            overwrite: Allow replacing an existing handler from the same plugin.
        """
        normalized_hook_name = (hook_name or "").strip().lower()
        if not normalized_hook_name:
            raise ValueError("hook_name is required")
        with self._lock:
            bucket = self._hook_handlers.setdefault(normalized_hook_name, {})
            if plugin_name in bucket and not overwrite:
                raise ValueError(
                    f"Hook already registered for plugin={plugin_name}: {normalized_hook_name}"
                )
            bucket[plugin_name] = (priority, handler)
            self._hook_metadata[(plugin_name, normalized_hook_name)] = RegisteredHookMetadata(
                plugin_name=plugin_name,
                hook_name=normalized_hook_name,
                display_name=display_name or normalized_hook_name.replace("_", " ").title(),
                description=description,
                default_priority=priority,
                default_enabled=default_enabled,
                default_settings=dict(default_settings or {}),
                settings_schema=dict(settings_schema or {}),
            )

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
        service: Any,
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
        provider: Any,
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

    def list_tool_factories(self) -> dict[str, PluginToolFactory]:
        """Return a snapshot of registered tool factories."""
        with self._lock:
            return dict(self._tool_factories)

    def list_sandbox_tool_factories(self) -> dict[str, list[PluginToolFactory]]:
        """Return a snapshot of registered sandbox tool factories."""
        with self._lock:
            return {k: list(v) for k, v in self._sandbox_tool_factories.items()}

    def list_skill_factories(self) -> dict[str, PluginSkillFactory]:
        """Return a snapshot of registered skill factories."""
        with self._lock:
            return dict(self._skill_factories)

    def list_channel_adapter_factories(self) -> dict[str, tuple[str, ChannelAdapterFactory]]:
        """Return a snapshot of channel adapter factories keyed by channel_type."""
        with self._lock:
            return dict(self._channel_adapter_factories)

    def list_channel_type_metadata(self) -> dict[str, ChannelTypeConfigMetadata]:
        """Return channel configuration metadata keyed by channel_type."""
        with self._lock:
            return dict(self._channel_type_metadata)

    def list_hooks(self) -> dict[str, dict[str, tuple[int, PluginHookHandler]]]:
        """Return registered hook handlers grouped by hook name.

        Each entry maps *plugin_name* to a ``(priority, handler)`` tuple.
        """
        with self._lock:
            return {
                hook_name: dict(handlers) for hook_name, handlers in self._hook_handlers.items()
            }

    def list_hook_catalog(self) -> list[RegisteredHookMetadata]:
        """Return catalog metadata for all registered runtime hooks."""
        with self._lock:
            metadata = list(self._hook_metadata.values())
        return sorted(metadata, key=lambda item: (item.plugin_name, item.hook_name))

    @staticmethod
    def list_well_known_hooks() -> frozenset[str]:
        """Return the set of well-known hook names with documented semantics."""
        return WELL_KNOWN_HOOKS

    def list_commands(self) -> dict[str, tuple[str, PluginCommandHandler]]:
        """Return command handlers keyed by command name."""
        with self._lock:
            return dict(self._commands)

    def list_services(self) -> dict[str, tuple[str, Any]]:
        """Return registered services keyed by service name."""
        with self._lock:
            return dict(self._services)

    def list_providers(self) -> dict[str, tuple[str, Any]]:
        """Return registered providers keyed by provider name."""
        with self._lock:
            return dict(self._providers)

    def list_http_routes(self) -> dict[str, list[PluginHttpRoute]]:
        """Return registered HTTP routes grouped by plugin name."""
        with self._lock:
            return {plugin: list(routes) for plugin, routes in self._http_routes.items()}

    def list_cli_commands(self) -> dict[str, list[PluginCliCommand]]:
        """Return registered CLI commands grouped by plugin name."""
        with self._lock:
            return {plugin: list(cmds) for plugin, cmds in self._cli_commands.items()}

    def register_lifecycle_hook(
        self,
        plugin_name: str,
        event: str,
        handler: PluginLifecycleHandler,
    ) -> None:
        """Register a lifecycle hook handler for a plugin."""
        normalized_event = (event or "").strip().lower()
        if normalized_event not in LIFECYCLE_EVENTS:
            raise ValueError(
                f"Unknown lifecycle event '{normalized_event}'. "
                f"Expected one of: {sorted(LIFECYCLE_EVENTS)}"
            )
        with self._lock:
            bucket = self._lifecycle_hooks.setdefault(normalized_event, {})
            bucket[plugin_name] = handler

    async def notify_lifecycle(
        self,
        event: str,
        *,
        plugin_names: list[str] | None = None,
    ) -> list[PluginDiagnostic]:
        """Invoke lifecycle handlers for the given event."""
        normalized_event = (event or "").strip().lower()
        if normalized_event not in LIFECYCLE_EVENTS:
            return []

        with self._lock:
            raw_handlers = dict(self._lifecycle_hooks.get(normalized_event, {}))

        diagnostics: list[PluginDiagnostic] = []
        for plugin_name, handler in raw_handlers.items():
            if plugin_names is not None and plugin_name not in plugin_names:
                continue
            try:
                result = handler()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="lifecycle_hook_failed",
                        message=f"{normalized_event}: {exc}",
                        level="error",
                    )
                )
        return diagnostics

    def list_lifecycle_hooks(self) -> dict[str, dict[str, PluginLifecycleHandler]]:
        """Return registered lifecycle hooks grouped by event name."""
        with self._lock:
            return {event: dict(handlers) for event, handlers in self._lifecycle_hooks.items()}

    async def apply_hook(
        self,
        hook_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
        runtime_overrides: list[Mapping[str, Any]] | None = None,
    ) -> HookDispatchResult:
        """Invoke named hook handlers and return the mutated payload."""
        normalized_name = (hook_name or "").strip().lower()
        if not normalized_name:
            return HookDispatchResult(payload=dict(payload or {}))

        with self._lock:
            raw_handlers = dict(self._hook_handlers.get(normalized_name, {}))
            raw_metadata = {
                plugin_name: self._hook_metadata.get((plugin_name, normalized_name))
                for plugin_name in raw_handlers
            }

        override_map: dict[tuple[str, str], dict[str, Any]] = {}
        for raw_override in runtime_overrides or []:
            plugin_name = str(raw_override.get("plugin_name", "")).strip().lower()
            override_hook_name = str(raw_override.get("hook_name", "")).strip().lower()
            if not plugin_name or not override_hook_name:
                continue
            override_map[(plugin_name, override_hook_name)] = dict(raw_override)

        sorted_handlers = sorted(
            raw_handlers.items(),
            key=lambda item: (
                override_map.get((item[0], normalized_name), {}).get("priority", item[1][0]),
            ),
        )

        current_payload = dict(payload or {})
        diagnostics: list[PluginDiagnostic] = []
        for plugin_name, (default_priority, handler) in sorted_handlers:
            override = override_map.get((plugin_name, normalized_name), {})
            if override and not bool(override.get("enabled", True)):
                continue

            metadata = raw_metadata.get(plugin_name)
            effective_settings = {}
            if metadata is not None:
                effective_settings.update(metadata.default_settings)
            override_settings = override.get("settings")
            if isinstance(override_settings, dict):
                effective_settings.update(override_settings)

            hook_payload = dict(current_payload)
            hook_payload["hook_settings"] = effective_settings
            hook_payload["hook_identity"] = {
                "plugin_name": plugin_name,
                "hook_name": normalized_name,
                "priority": override.get("priority", default_priority),
            }
            try:
                result = handler(hook_payload)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, Mapping):
                    current_payload = dict(result)
            except Exception as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="hook_handler_failed",
                        message=f"{normalized_name}: {exc}",
                        level="error",
                    )
                )

        return HookDispatchResult(payload=current_payload, diagnostics=diagnostics)

    async def notify_hook(
        self,
        hook_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
        runtime_overrides: list[Mapping[str, Any]] | None = None,
    ) -> list[PluginDiagnostic]:
        """Invoke named hook handlers and discard payload mutations."""
        result = await self.apply_hook(
            hook_name,
            payload=payload,
            runtime_overrides=runtime_overrides,
        )
        return result.diagnostics

    async def execute_command(
        self,
        command_name: str,
        *,
        payload: Mapping[str, Any] | None = None,
    ) -> tuple[Any, list[PluginDiagnostic]]:
        """Execute one registered plugin command."""
        normalized_name = (command_name or "").strip().lower()
        if not normalized_name:
            return None, []

        with self._lock:
            command_entry = self._commands.get(normalized_name)
        if not command_entry:
            return None, []

        plugin_name, handler = command_entry
        diagnostics: list[PluginDiagnostic] = []
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

    def get_service(self, service_name: str) -> Any:
        """Get a service by name if registered."""
        normalized_name = (service_name or "").strip().lower()
        if not normalized_name:
            return None
        with self._lock:
            service_entry = self._services.get(normalized_name)
        if not service_entry:
            return None
        return service_entry[1]

    def get_provider(self, provider_name: str) -> Any:
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
    ) -> tuple[dict[str, Any], list[PluginDiagnostic]]:
        """Build plugin-provided tools for the given context."""
        tool_factories = self.list_tool_factories()
        diagnostics: list[PluginDiagnostic] = []
        plugin_tools: dict[str, Any] = {}

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
                    # Tag tool with originating plugin name for downstream adaptation
                    if not isinstance(tool_impl, ToolInfo):
                        with contextlib.suppress(AttributeError, TypeError):
                            tool_impl._plugin_origin = plugin_name
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

    async def build_skills(
        self,
        context: PluginSkillBuildContext,
    ) -> tuple[list[dict[str, Any]], list[PluginDiagnostic]]:
        """Build plugin-provided skill definitions for the given context."""
        skill_factories = self.list_skill_factories()
        diagnostics: list[PluginDiagnostic] = []
        plugin_skills: list[dict[str, Any]] = []

        for plugin_name, factory in skill_factories.items():
            try:
                produced = factory(context)
                if inspect.isawaitable(produced):
                    produced = await produced
                if not isinstance(produced, list):
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="invalid_skill_factory_result",
                            message="Skill factory must return list[dict[str, Any]]",
                            level="error",
                        )
                    )
                    continue
                plugin_skills.extend(produced)
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_skills_loaded",
                        message=f"Registered {len(produced)} plugin skill(s)",
                        level="info",
                    )
                )
            except Exception as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="skill_factory_failed",
                        message=str(exc),
                        level="error",
                    )
                )

        return plugin_skills, diagnostics

    async def notify_channel_reload(
        self,
        *,
        plan_summary: dict[str, int],
        dry_run: bool,
    ) -> list[PluginDiagnostic]:
        """Notify registered plugins about channel reload planning/execution."""
        with self._lock:
            hooks = dict(self._channel_reload_hooks)

        diagnostics: list[PluginDiagnostic] = []
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
    ) -> tuple[Any | None, list[PluginDiagnostic]]:
        """Build a channel adapter from plugin factory for the requested channel_type."""
        channel_type = (context.channel_type or "").strip().lower()
        if not channel_type:
            return None, []

        with self._lock:
            factory_entry = self._channel_adapter_factories.get(channel_type)

        if not factory_entry:
            return None, []

        plugin_name, factory = factory_entry
        diagnostics: list[PluginDiagnostic] = []
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

    def register_subagent_resolver_factory(
        self,
        plugin_name: str,
        factory: SubAgentResolverFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a sub-agent resolver factory for a plugin.

        The factory is called during ``SubAgentRouter`` initialisation and
        should return a ``Resolver`` instance (from
        ``src.infrastructure.agent.core.resolver``).
        """
        with self._lock:
            if plugin_name in self._subagent_resolver_factories and not overwrite:
                raise ValueError(
                    f"SubAgent resolver factory already registered for plugin: {plugin_name}"
                )
            self._subagent_resolver_factories[plugin_name] = factory

    async def build_subagent_resolvers(
        self,
        context: SubAgentResolverBuildContext,
    ) -> tuple[list[Any], list[PluginDiagnostic]]:
        """Invoke all registered resolver factories and collect results.

        Returns a tuple of (resolvers, diagnostics).
        """
        with self._lock:
            factories = dict(self._subagent_resolver_factories)

        resolvers: list[Any] = []
        diagnostics: list[PluginDiagnostic] = []
        for plugin_name, factory in factories.items():
            try:
                result = factory(context)
                if inspect.isawaitable(result):
                    result = await result
                if result is not None:
                    resolvers.append(result)
            except Exception as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="subagent_resolver_factory_failed",
                        message=str(exc),
                        level="error",
                    )
                )
        return resolvers, diagnostics

    def clear(self) -> None:
        """Clear registry state (primarily for tests)."""
        with self._lock:
            self._tool_factories.clear()
            self._channel_reload_hooks.clear()
            self._channel_adapter_factories.clear()
            self._channel_type_metadata.clear()
            self._hook_handlers.clear()
            self._hook_metadata.clear()
            self._commands.clear()
            self._services.clear()
            self._providers.clear()
            self._skill_factories.clear()
            self._http_routes.clear()
            self._cli_commands.clear()
            self._lifecycle_hooks.clear()
            self._config_schemas.clear()
            self._sandbox_tool_factories.clear()
            self._subagent_resolver_factories.clear()

    def register_config_schema(self, plugin_name: str, schema: dict[str, Any]) -> None:
        """Register a JSON Schema for validating a plugin's configuration."""
        if not isinstance(schema, dict) or not schema:
            raise ValueError("schema must be a non-empty dict")
        with self._lock:
            self._config_schemas[plugin_name] = PluginConfigSchema(
                plugin_name=plugin_name,
                schema=dict(schema),
            )

    def validate_config(self, plugin_name: str, config: dict[str, Any]) -> list[PluginDiagnostic]:
        """Validate plugin config against its registered JSON Schema."""
        with self._lock:
            entry = self._config_schemas.get(plugin_name)
        if entry is None:
            return []
        diagnostics: list[PluginDiagnostic] = []
        try:
            jsonschema.validate(instance=config, schema=entry.schema)
        except jsonschema.ValidationError as exc:
            diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin_name,
                    code="config_validation_failed",
                    message=str(exc.message),
                    level="error",
                )
            )
        except jsonschema.SchemaError as exc:
            diagnostics.append(
                PluginDiagnostic(
                    plugin_name=plugin_name,
                    code="config_schema_invalid",
                    message=str(exc.message),
                    level="error",
                )
            )
        return diagnostics

    def list_config_schemas(self) -> dict[str, PluginConfigSchema]:
        """Return a snapshot of registered config schemas."""
        with self._lock:
            return dict(self._config_schemas)


_global_plugin_registry = AgentPluginRegistry()


def _register_builtin_hooks() -> None:
    """Ensure built-in runtime hooks are registered exactly once."""
    if any(
        entry.plugin_name == "sisyphus-runtime"
        for entry in _global_plugin_registry.list_hook_catalog()
    ):
        return
    from src.infrastructure.agent.sisyphus.runtime_plugin import (
        register_builtin_sisyphus_plugin,
    )

    register_builtin_sisyphus_plugin(_global_plugin_registry)


def get_plugin_registry() -> AgentPluginRegistry:
    """Get the global plugin registry singleton."""
    _register_builtin_hooks()
    return _global_plugin_registry
