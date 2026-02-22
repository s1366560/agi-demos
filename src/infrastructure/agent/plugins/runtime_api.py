"""Runtime API exposed to plugins."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .registry import (
    AgentPluginRegistry,
    ChannelAdapterFactory,
    ChannelReloadHook,
    PluginToolFactory,
    get_plugin_registry,
)


class PluginRuntimeApi:
    """API surface available to plugin setup hooks."""

    def __init__(
        self,
        plugin_name: str,
        *,
        registry: Optional[AgentPluginRegistry] = None,
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
        config_schema: Optional[Dict[str, Any]] = None,
        config_ui_hints: Optional[Dict[str, Any]] = None,
        defaults: Optional[Dict[str, Any]] = None,
        secret_paths: Optional[List[str]] = None,
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
        config_schema: Optional[Dict[str, Any]] = None,
        config_ui_hints: Optional[Dict[str, Any]] = None,
        defaults: Optional[Dict[str, Any]] = None,
        secret_paths: Optional[List[str]] = None,
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
