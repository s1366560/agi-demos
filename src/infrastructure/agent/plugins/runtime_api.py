"""Runtime API exposed to plugins."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    from .sandbox_deps.models import RuntimeDependencies


class PluginRuntimeApi:
    """API surface available to plugin setup hooks."""

    def __init__(
        self,
        plugin_name: str,
        *,
        registry: AgentPluginRegistry | None = None,
    ) -> None:
        self._plugin_name = plugin_name
        self._registry = registry or get_plugin_registry()

    def register_tool_factory(
        self,
        factory: PluginToolFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a tool factory for this plugin."""
        self._registry.register_tool_factory(self._plugin_name, factory, overwrite=overwrite)

    def register_skill_factory(
        self,
        factory: PluginSkillFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a skill factory for this plugin."""
        self._registry.register_skill_factory(self._plugin_name, factory, overwrite=overwrite)

    def register_http_route(
        self,
        method: str,
        path: str,
        handler: PluginHttpHandler,
        *,
        summary: str | None = None,
        tags: list[str] | None = None,
    ) -> None:
        """Register an HTTP route for this plugin."""
        self._registry.register_http_route(
            self._plugin_name,
            method,
            path,
            handler,
            summary=summary,
            tags=tags,
        )

    def register_cli_command(
        self,
        name: str,
        handler: PluginCliHandler,
        *,
        description: str | None = None,
        args_schema: dict[str, Any] | None = None,
    ) -> None:
        """Register a CLI command for this plugin."""
        self._registry.register_cli_command(
            self._plugin_name,
            name,
            handler,
            description=description,
            args_schema=args_schema,
        )

    def register_channel_reload_hook(
        self,
        hook: ChannelReloadHook,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a channel reload hook for this plugin."""
        self._registry.register_channel_reload_hook(self._plugin_name, hook, overwrite=overwrite)

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
        """Register a channel adapter factory for this plugin."""
        self._registry.register_channel_adapter_factory(
            self._plugin_name,
            channel_type,
            factory,
            config_schema=config_schema,
            config_ui_hints=config_ui_hints,
            defaults=defaults,
            secret_paths=secret_paths,
            overwrite=overwrite,
        )

    def register_channel_type(
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
        """Register channel adapter and optional config metadata for this plugin."""
        self.register_channel_adapter_factory(
            channel_type,
            factory,
            config_schema=config_schema,
            config_ui_hints=config_ui_hints,
            defaults=defaults,
            secret_paths=secret_paths,
            overwrite=overwrite,
        )

    def register_hook(
        self,
        hook_name: str,
        handler: PluginHookHandler,
        *,
        priority: int = 100,
        overwrite: bool = False,
    ) -> None:
        """Register a named runtime hook handler.

        Args:
            hook_name: Hook point name (see ``WELL_KNOWN_HOOKS`` for documented names).
            handler: Async or sync callable invoked when the hook fires.
            priority: Numeric priority -- lower values run first.  Default ``100``.
            overwrite: Allow replacing an existing handler from this plugin.
        """
        self._registry.register_hook(
            self._plugin_name,
            hook_name,
            handler,
            priority=priority,
            overwrite=overwrite,
        )

    def register_command(
        self,
        command_name: str,
        handler: PluginCommandHandler,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a command handler for runtime invocation."""
        self._registry.register_command(
            self._plugin_name,
            command_name,
            handler,
            overwrite=overwrite,
        )

    def register_service(
        self,
        service_name: str,
        service: Any,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a plugin service object."""
        self._registry.register_service(
            self._plugin_name,
            service_name,
            service,
            overwrite=overwrite,
        )

    def register_provider(
        self,
        provider_name: str,
        provider: Any,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a provider object for runtime lookup."""
        self._registry.register_provider(
            self._plugin_name,
            provider_name,
            provider,
            overwrite=overwrite,
        )

    def register_lifecycle_hook(
        self,
        event: str,
        handler: PluginLifecycleHandler,
    ) -> None:
        """Register a lifecycle hook handler for this plugin."""
        self._registry.register_lifecycle_hook(self._plugin_name, event, handler)

    def register_config_schema(self, schema: dict[str, Any]) -> None:
        """Register a JSON Schema for validating this plugin's configuration."""
        self._registry.register_config_schema(self._plugin_name, schema)

    def register_sandbox_tool_factory(
        self,
        factory: PluginToolFactory,
        *,
        overwrite: bool = False,
    ) -> None:
        """Register a sandbox tool factory for this plugin."""
        self._registry.register_sandbox_tool_factory(
            self._plugin_name, factory, overwrite=overwrite
        )

    def declare_sandbox_dependencies(
        self,
        dependencies: RuntimeDependencies,
    ) -> None:
        """Declare sandbox-side dependencies for this plugin.

        This is a convenience method that stores the dependency manifest
        in the registry as a service, allowing the orchestrator to retrieve
        it when building sandbox tools.
        """
        self._registry.register_service(
            self._plugin_name,
            f"{self._plugin_name}:sandbox_deps",
            dependencies,
            overwrite=True,
        )

    def get_sandbox_dependencies(self) -> RuntimeDependencies | None:
        """Retrieve previously declared sandbox dependencies for this plugin."""
        from .sandbox_deps.models import RuntimeDependencies as RTDeps

        result = self._registry.get_service(f"{self._plugin_name}:sandbox_deps")
        if result is None:
            return None
        if isinstance(result, RTDeps):
            return result
        return None
