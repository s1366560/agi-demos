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

from src.domain.model.agent.tenant_agent_config import HookExecutorKind
from src.infrastructure.agent.plugins.custom_hook_executor import execute_custom_hook
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
        "before_prompt_build",
        "before_tool_selection",
        "after_tool_selection",
        "before_tool_execution",
        "after_tool_execution",
        "before_response",
        "after_response",
        "after_turn_complete",
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

HOOK_FAMILY_BY_NAME: dict[str, str] = {
    "before_prompt_build": "mutating",
    "on_session_start": "mutating",
    "on_session_end": "side_effect",
    "before_response": "mutating",
    "after_response": "side_effect",
    "after_turn_complete": "mutating",
    "before_tool_selection": "mutating",
    "after_tool_selection": "side_effect",
    "before_tool_execution": "policy",
    "after_tool_execution": "mutating",
    "before_planning": "mutating",
    "after_planning": "side_effect",
    "on_error": "side_effect",
    "on_context_overflow": "mutating",
    "before_subagent_spawn": "policy",
    "after_subagent_spawn": "side_effect",
    "before_subagent_complete": "side_effect",
    "after_subagent_complete": "side_effect",
    "on_subagent_doom_loop": "side_effect",
    "on_subagent_routed": "side_effect",
}

HOOK_DISPLAY_NAME_BY_NAME: dict[str, str] = {
    hook_name: hook_name.replace("_", " ").title() for hook_name in WELL_KNOWN_HOOKS
}

HOOK_DEFAULT_DESCRIPTION_BY_NAME: dict[str, str] = {
    "before_prompt_build": "Runs after pre-prompt preparation and may adjust prompt-bound payloads.",
    "before_tool_execution": "Runs before tool execution and may request continue / deny / ask decisions.",
    "after_tool_execution": "Runs after tool execution to mutate follow-up payloads or emit side effects.",
    "before_response": "Runs before the model drafts a response and may adjust response payloads.",
    "after_turn_complete": "Runs after a turn completes to emit side effects such as indexing or durable capture.",
    "on_session_start": "Runs at the start of a processor session.",
    "on_error": "Runs when the processor catches an error.",
    "before_subagent_spawn": "Runs before a subagent starts and may enforce policy decisions.",
    "after_subagent_complete": "Runs after a subagent completes.",
}


def _normalize_hook_name(value: str) -> str:
    """Normalize a hook name for storage and comparison."""
    return (value or "").strip().lower()


def _infer_hook_family(hook_name: str) -> str:
    """Infer the canonical family for a hook name."""
    return HOOK_FAMILY_BY_NAME.get(_normalize_hook_name(hook_name), "mutating")


@dataclass(frozen=True)
class PluginToolBuildContext:
    """Build context passed to plugin tool factories."""

    tenant_id: str
    project_id: str
    base_tools: dict[str, Any]
    graph_service: Any | None = None
    redis_client: Any | None = None
    session_factory: Any | None = None


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
    hook_family: str
    display_name: str
    description: str | None = None
    default_priority: int = 100
    default_enabled: bool = True
    default_executor_kind: str = HookExecutorKind.BUILTIN.value
    default_source_ref: str | None = None
    default_entrypoint: str | None = None
    default_settings: dict[str, Any] = field(default_factory=dict)
    settings_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HookDispatchResult:
    """Hook execution result including the final payload and diagnostics."""

    payload: dict[str, Any]
    diagnostics: list[PluginDiagnostic] = field(default_factory=list)


@dataclass(frozen=True)
class _ResolvedHookEntry:
    """Resolved runtime hook entry ready for execution."""

    entry_type: str
    plugin_name: str
    enabled: bool
    priority: int
    hook_family: str
    executor_kind: str
    source_ref: str | None
    entrypoint: str | None
    effective_settings: dict[str, Any]
    handler: PluginHookHandler | None = None


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
        hook_family: str | None = None,
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
        normalized_hook_name = _normalize_hook_name(hook_name)
        if not normalized_hook_name:
            raise ValueError("hook_name is required")
        resolved_hook_family = _infer_hook_family(hook_family or normalized_hook_name)
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
                hook_family=resolved_hook_family,
                display_name=display_name
                or HOOK_DISPLAY_NAME_BY_NAME.get(
                    normalized_hook_name,
                    normalized_hook_name.replace("_", " ").title(),
                ),
                description=description
                or HOOK_DEFAULT_DESCRIPTION_BY_NAME.get(normalized_hook_name),
                default_priority=priority,
                default_enabled=default_enabled,
                default_executor_kind=HookExecutorKind.BUILTIN.value,
                default_source_ref=plugin_name,
                default_entrypoint=None,
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

    @staticmethod
    def _collect_runtime_overrides(
        normalized_name: str,
        runtime_overrides: list[Mapping[str, Any]] | None,
    ) -> tuple[dict[tuple[str, str], dict[str, Any]], list[dict[str, Any]]]:
        """Partition runtime overrides into builtin and custom entries."""
        override_map: dict[tuple[str, str], dict[str, Any]] = {}
        custom_entries: list[dict[str, Any]] = []
        for raw_override in runtime_overrides or []:
            override_hook_name = _normalize_hook_name(str(raw_override.get("hook_name", "")))
            if override_hook_name != normalized_name:
                continue
            override = dict(raw_override)
            executor_kind = str(
                override.get("executor_kind", HookExecutorKind.BUILTIN.value)
            ).strip().lower()
            plugin_name = str(override.get("plugin_name", "")).strip().lower()
            if executor_kind == HookExecutorKind.BUILTIN.value:
                if plugin_name:
                    override_map[(plugin_name, override_hook_name)] = override
                continue
            custom_entries.append(override)
        return override_map, custom_entries

    @staticmethod
    def _build_effective_settings(
        metadata: RegisteredHookMetadata | None,
        override: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge default and override settings for one hook entry."""
        effective_settings: dict[str, Any] = {}
        if metadata is not None:
            effective_settings.update(metadata.default_settings)
        override_settings = override.get("settings")
        if isinstance(override_settings, dict):
            effective_settings.update(override_settings)
        return effective_settings

    @staticmethod
    def _is_plugin_enabled(
        plugin_name: str,
        *,
        tenant_id: str | None,
    ) -> bool:
        """Best-effort plugin enablement check using the runtime manager state store."""
        if not plugin_name or plugin_name == "__custom__":
            return True
        try:
            from src.infrastructure.agent.plugins.manager import get_plugin_runtime_manager

            return get_plugin_runtime_manager().is_plugin_enabled(
                plugin_name,
                tenant_id=tenant_id,
            )
        except Exception:
            return True

    def _resolve_hook_entries(
        self,
        *,
        normalized_name: str,
        raw_handlers: dict[str, tuple[int, PluginHookHandler]],
        raw_metadata: dict[str, RegisteredHookMetadata | None],
        override_map: dict[tuple[str, str], dict[str, Any]],
        custom_entries: list[dict[str, Any]],
    ) -> list[_ResolvedHookEntry]:
        """Resolve registered and custom hook entries into one ordered list."""
        entries: list[_ResolvedHookEntry] = []
        for plugin_name, (default_priority, handler) in raw_handlers.items():
            override = override_map.get((plugin_name, normalized_name), {})
            override_priority = override.get("priority")
            metadata = raw_metadata.get(plugin_name)
            entries.append(
                _ResolvedHookEntry(
                    entry_type="registered",
                    plugin_name=plugin_name,
                    enabled=bool(override.get("enabled", True)),
                    priority=int(override_priority)
                    if override_priority is not None
                    else default_priority,
                    hook_family=str(
                        override.get(
                            "hook_family",
                            metadata.hook_family if metadata is not None else _infer_hook_family(normalized_name),
                        )
                    ).strip().lower(),
                    executor_kind=str(
                        override.get(
                            "executor_kind",
                            metadata.default_executor_kind
                            if metadata is not None
                            else HookExecutorKind.BUILTIN.value,
                        )
                    ).strip().lower(),
                    source_ref=(
                        str(override["source_ref"]).strip()
                        if override.get("source_ref") is not None
                        else (metadata.default_source_ref if metadata is not None else None)
                    ),
                    entrypoint=(
                        str(override["entrypoint"]).strip()
                        if override.get("entrypoint") is not None
                        else (metadata.default_entrypoint if metadata is not None else None)
                    ),
                    effective_settings=self._build_effective_settings(metadata, override),
                    handler=handler,
                )
            )

        for override in custom_entries:
            raw_priority = override.get("priority")
            plugin_name = str(override.get("plugin_name", "")).strip() or str(
                override.get("source_ref", "custom-hook")
            ).strip()
            entries.append(
                _ResolvedHookEntry(
                    entry_type="custom",
                    plugin_name=plugin_name,
                    enabled=bool(override.get("enabled", True)),
                    priority=int(raw_priority) if raw_priority is not None else 100,
                    hook_family=str(
                        override.get("hook_family") or _infer_hook_family(normalized_name)
                    ).strip().lower(),
                    executor_kind=str(
                        override.get("executor_kind", HookExecutorKind.BUILTIN.value)
                    ).strip().lower(),
                    source_ref=str(override.get("source_ref", "")).strip() or None,
                    entrypoint=str(override.get("entrypoint", "")).strip() or None,
                    effective_settings=self._build_effective_settings(None, override),
                )
            )
        return sorted(entries, key=lambda item: item.priority)

    @staticmethod
    def _build_hook_payload(
        *,
        current_payload: dict[str, Any],
        normalized_name: str,
        entry: _ResolvedHookEntry,
    ) -> dict[str, Any]:
        """Build the runtime payload passed to one hook entry."""
        hook_payload = dict(current_payload)
        hook_payload["hook_settings"] = entry.effective_settings
        hook_payload["hook_identity"] = {
            "plugin_name": entry.plugin_name,
            "hook_name": normalized_name,
            "priority": entry.priority,
            "executor_kind": entry.executor_kind,
            "source_ref": entry.source_ref,
            "entrypoint": entry.entrypoint,
        }
        hook_payload["hook_family"] = entry.hook_family
        return hook_payload

    @staticmethod
    async def _execute_hook_entry(
        entry: _ResolvedHookEntry,
        hook_payload: dict[str, Any],
    ) -> Mapping[str, Any] | None:
        """Execute one resolved hook entry."""
        if entry.entry_type == "custom":
            return await execute_custom_hook(
                executor_kind=entry.executor_kind,
                source_ref=str(entry.source_ref or ""),
                entrypoint=str(entry.entrypoint or ""),
                hook_family=entry.hook_family,
                payload=hook_payload,
            )
        if entry.handler is None:
            return None
        result = entry.handler(hook_payload)
        if inspect.isawaitable(result):
            result = await result
        return result if isinstance(result, Mapping) else None

    @staticmethod
    def _apply_hook_result_by_family(
        current_payload: dict[str, Any],
        result: Mapping[str, Any] | None,
        *,
        hook_family: str,
    ) -> dict[str, Any]:
        """Apply a hook result while enforcing family capabilities."""
        if not isinstance(result, Mapping):
            return current_payload
        normalized_family = (hook_family or "").strip().lower()
        if normalized_family in {"observational", "side_effect"}:
            return current_payload
        return dict(result)

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
        normalized_name = _normalize_hook_name(hook_name)
        if not normalized_name:
            return HookDispatchResult(payload=dict(payload or {}))

        with self._lock:
            raw_handlers = dict(self._hook_handlers.get(normalized_name, {}))
            raw_metadata = {
                plugin_name: self._hook_metadata.get((plugin_name, normalized_name))
                for plugin_name in raw_handlers
            }

        override_map, custom_entries = self._collect_runtime_overrides(
            normalized_name,
            runtime_overrides,
        )
        ordered_entries = self._resolve_hook_entries(
            normalized_name=normalized_name,
            raw_handlers=raw_handlers,
            raw_metadata=raw_metadata,
            override_map=override_map,
            custom_entries=custom_entries,
        )

        current_payload = dict(payload or {})
        tenant_id = str(current_payload.get("tenant_id")) if current_payload.get("tenant_id") else None
        diagnostics: list[PluginDiagnostic] = []
        for entry in ordered_entries:
            plugin_name = entry.plugin_name
            if not self._is_plugin_enabled(plugin_name, tenant_id=tenant_id):
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_disabled",
                        message=f"Skipped disabled plugin: {plugin_name}",
                        level="info",
                    )
                )
                continue
            if not entry.enabled:
                continue

            hook_payload = self._build_hook_payload(
                current_payload=current_payload,
                normalized_name=normalized_name,
                entry=entry,
            )
            try:
                result = await self._execute_hook_entry(entry, hook_payload)
                current_payload = self._apply_hook_result_by_family(
                    current_payload,
                    result,
                    hook_family=entry.hook_family,
                )
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
            if not self._is_plugin_enabled(plugin_name, tenant_id=context.tenant_id):
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_disabled",
                        message=f"Skipped disabled plugin: {plugin_name}",
                        level="info",
                    )
                )
                continue
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
            if not self._is_plugin_enabled(plugin_name, tenant_id=context.tenant_id):
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_disabled",
                        message=f"Skipped disabled plugin: {plugin_name}",
                        level="info",
                    )
                )
                continue
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
    """Ensure built-in runtime plugins are registered exactly once."""
    from src.configuration.config import get_settings
    from src.infrastructure.agent.plugins.memory_plugin import (
        register_builtin_memory_plugin,
    )
    from src.infrastructure.agent.sisyphus.runtime_plugin import (
        register_builtin_sisyphus_plugin,
    )
    from src.infrastructure.agent.workspace.runtime_plugin import (
        register_builtin_workspace_plugin,
    )

    hook_catalog = _global_plugin_registry.list_hook_catalog()
    if not any(entry.plugin_name == "workspace-runtime" for entry in hook_catalog):
        register_builtin_workspace_plugin(_global_plugin_registry)
    if not any(entry.plugin_name == "sisyphus-runtime" for entry in hook_catalog):
        register_builtin_sisyphus_plugin(_global_plugin_registry)
    if (
        get_settings().agent_memory_runtime_mode != "disabled"
        and not any(entry.plugin_name == "memory-runtime" for entry in hook_catalog)
    ):
        register_builtin_memory_plugin(_global_plugin_registry)
    if not any(entry.plugin_name == "skill-evolution" for entry in hook_catalog):
        _register_skill_evolution_hook(_global_plugin_registry)


def _register_skill_evolution_hook(registry: AgentPluginRegistry) -> None:
    """Register the skill evolution after_turn_complete hook.

    This only registers the hook; the full plugin (with scheduler,
    LLM client, and skill service) is initialized later via the DI
    container when those dependencies are available.
    """
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi
    from src.infrastructure.agent.plugins.skill_evolution.plugin import (
        _after_turn_complete,
    )

    api = PluginRuntimeApi("skill-evolution", registry=registry)
    api.register_hook(
        "after_turn_complete",
        _after_turn_complete,
        hook_family="mutating",
        priority=30,
        display_name="Skill evolution capture",
        description=(
            "Captures skill-execution data after each turn for "
            "periodic evolution analysis and SKILL.md improvement."
        ),
        overwrite=True,
    )


def get_plugin_registry() -> AgentPluginRegistry:
    """Get the global plugin registry singleton."""
    _register_builtin_hooks()
    return _global_plugin_registry
