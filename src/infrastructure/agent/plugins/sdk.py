"""High-level convenience SDK wrapping PluginRuntimeApi."""

from __future__ import annotations

from typing import Any

from .registry import (
    AgentPluginRegistry,
    ChannelAdapterFactory,
    ChannelReloadHook,
    PluginCliHandler,
    PluginCommandHandler,
    PluginHookHandler,
    PluginHttpHandler,
    PluginLifecycleHandler,
    PluginSkillFactory,
    PluginToolFactory,
    get_plugin_registry,
)
from .runtime_api import PluginRuntimeApi


class PluginSDK:
    """Convenience wrapper around :class:`PluginRuntimeApi`.

    Provides the same registration surface plus shorthand helpers
    for common patterns such as lifecycle hooks and typed tool
    registration.
    """

    def __init__(
        self,
        plugin_name: str,
        *,
        registry: AgentPluginRegistry | None = None,
    ) -> None:
        self._plugin_name = plugin_name
        self._api = PluginRuntimeApi(
            plugin_name,
            registry=registry or get_plugin_registry(),
        )

    @property
    def name(self) -> str:
        """Return the plugin name."""
        return self._plugin_name

    @property
    def api(self) -> PluginRuntimeApi:
        """Return the underlying runtime API."""
        return self._api

    # ------------------------------------------------------------------
    # Delegation helpers
    # ------------------------------------------------------------------

    def register_tool_factory(
        self,
        factory: PluginToolFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a tool factory for this plugin."""
        self._api.register_tool_factory(factory, overwrite=overwrite)

    def register_skill_factory(
        self,
        factory: PluginSkillFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a skill factory for this plugin."""
        self._api.register_skill_factory(factory, overwrite=overwrite)

    def register_hook(
        self,
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
        """Register a runtime hook handler."""
        self._api.register_hook(
            hook_name,
            handler,
            priority=priority,
            display_name=display_name,
            description=description,
            default_enabled=default_enabled,
            default_settings=default_settings,
            settings_schema=settings_schema,
            overwrite=overwrite,
        )

    def register_command(
        self,
        command_name: str,
        handler: PluginCommandHandler,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a command handler."""
        self._api.register_command(command_name, handler, overwrite=overwrite)

    def register_service(
        self,
        service_name: str,
        service: Any,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a service object."""
        self._api.register_service(service_name, service, overwrite=overwrite)

    def register_provider(
        self,
        provider_name: str,
        provider: Any,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a provider object."""
        self._api.register_provider(provider_name, provider, overwrite=overwrite)

    def register_http_route(
        self,
        method: str,
        path: str,
        handler: PluginHttpHandler,
        *,
        summary: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register an HTTP route."""
        self._api.register_http_route(method, path, handler, summary=summary, tags=tags)

    def register_cli_command(
        self,
        name: str,
        handler: PluginCliHandler,
        *,
        description: str | None = None,
        args_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a CLI command."""
        self._api.register_cli_command(
            name, handler, description=description, args_schema=args_schema
        )

    def register_channel_reload_hook(
        self,
        hook: ChannelReloadHook,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a channel reload hook."""
        self._api.register_channel_reload_hook(hook, overwrite=overwrite)

    def register_channel_adapter_factory(
        self,
        channel_type: str,
        factory: ChannelAdapterFactory,
        *,
        config_schema: dict[str, Any] | None = None,
        config_ui_hints: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        secret_paths: list[str] | None = None,
        overwrite: bool = False,
    ) -> None:
        """Register a channel adapter factory."""
        self._api.register_channel_adapter_factory(
            channel_type,
            factory,
            config_schema=config_schema,
            config_ui_hints=config_ui_hints,
            defaults=defaults,
            secret_paths=secret_paths,
            overwrite=overwrite,
        )

    def register_config_schema(self, schema: dict[str, Any]) -> None:
        """Register a config schema for this plugin."""
        self._api.register_config_schema(schema)

    # ------------------------------------------------------------------
    # Lifecycle shorthand
    # ------------------------------------------------------------------

    def on_load(self, handler: PluginLifecycleHandler) -> None:
        """Register an ``on_load`` lifecycle handler."""
        self._api.register_lifecycle_hook("on_load", handler)

    def on_enable(self, handler: PluginLifecycleHandler) -> None:
        """Register an ``on_enable`` lifecycle handler."""
        self._api.register_lifecycle_hook("on_enable", handler)

    def on_disable(self, handler: PluginLifecycleHandler) -> None:
        """Register an ``on_disable`` lifecycle handler."""
        self._api.register_lifecycle_hook("on_disable", handler)

    def on_unload(self, handler: PluginLifecycleHandler) -> None:
        """Register an ``on_unload`` lifecycle handler."""
        self._api.register_lifecycle_hook("on_unload", handler)
