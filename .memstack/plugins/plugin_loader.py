"""Plugin Loading System - Enables plugins to provide tools, hooks, HTTP routes, etc.

This module provides the infrastructure for loading and managing plugins.
"""

import importlib
import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

# Plugin registry
_registered_plugins: dict[str, Any] = {}
_tool_factories: list[Callable] = []
_hooks: dict[str, list[tuple[int, Callable]]] = {}
_http_routes: list[tuple[str, str, Callable]] = []
_cli_commands: dict[str, Callable] = {}
_lifecycle_hooks: dict[str, list[Callable]] = {}
_services: dict[str, Any] = {}
_providers: dict[str, Any] = {}


def register_tool_factory(factory: Callable[[Any], dict[str, Any]]) -> None:
    """Register a tool factory function.

    The factory function receives a context object and returns a dict
    mapping tool names to tool instances.
    """
    _tool_factories.append(factory)


def register_hook(hook_name: str, handler: Callable, priority: int = 50) -> None:
    """Register a hook handler.

    Args:
        hook_name: Name of the hook (e.g., 'before_tool_execute')
        handler: Async function to call
        priority: Lower values run first (default: 50)
    """
    if hook_name not in _hooks:
        _hooks[hook_name] = []
    _hooks[hook_name].append((priority, handler))
    _hooks[hook_name].sort(key=lambda x: x[0])


def register_http_route(method: str, path: str, handler: Callable, **kwargs) -> None:
    """Register an HTTP route handler."""
    _http_routes.append((method.upper(), path, handler))


def register_cli_command(name: str, handler: Callable, **kwargs) -> None:
    """Register a CLI command."""
    _cli_commands[name] = handler


def register_lifecycle_hook(event: str, handler: Callable) -> None:
    """Register a lifecycle hook (on_load, on_enable, on_disable, on_unload)."""
    if event not in _lifecycle_hooks:
        _lifecycle_hooks[event] = []
    _lifecycle_hooks[event].append(handler)


def register_service(name: str, service: Any) -> None:
    """Register a service instance."""
    _services[name] = service


def register_provider(name: str, provider: Any) -> None:
    """Register a provider instance."""
    _providers[name] = provider


def register_config_schema(schema: dict) -> None:
    """Register plugin configuration schema."""
    # TODO: Implement config schema validation


def register_command(name: str, handler: Callable) -> None:
    """Register a named command."""
    _cli_commands[name] = handler


# ---------------------------------------------------------------------------
# Plugin Discovery & Loading
# ---------------------------------------------------------------------------

_PLUGINS_DIR = Path(__file__).parent


def discover_plugins() -> list[str]:
    """Discover available plugins in the plugins directory."""
    plugins = []
    if not _PLUGINS_DIR.exists():
        return plugins

    for item in _PLUGINS_DIR.iterdir():
        if item.is_dir() and (item / "memstack.plugin.json").exists():
            plugins.append(item.name)
    return plugins


def load_plugin(plugin_name: str) -> bool:
    """Load a plugin by name.

    Loads the plugin's module and calls its setup() function with the
    plugin API. Returns True if successful.
    """
    plugin_dir = _PLUGINS_DIR / plugin_name
    plugin_json = plugin_dir / "memstack.plugin.json"

    if not plugin_json.exists():
        print(f"Plugin {plugin_name}: memstack.plugin.json not found")
        return False

    # Load plugin config
    with open(plugin_json) as f:
        config = json.load(f)

    # Find main plugin file
    entry_point = config.get("entry", "plugin.py")
    plugin_file = plugin_dir / entry_point

    if not plugin_file.exists():
        print(f"Plugin {plugin_name}: entry point {entry_point} not found")
        return False

    # Load the module
    module_name = f"plugins.{plugin_name}.plugin"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        print(f"Plugin {plugin_name}: failed to load module spec")
        return False

    module = importlib.util.module_from_spec(spec)

    # Create plugin API
    class PluginAPI:
        """API object passed to plugin setup()"""

        def register_tool_factory(self, factory: Callable):
            register_tool_factory(factory)

        def register_hook(self, name: str, handler: Callable, priority: int = 50):
            register_hook(name, handler, priority)

        def register_http_route(self, method: str, path: str, handler: Callable, **kwargs):
            register_http_route(method, path, handler)

        def register_cli_command(self, name: str, handler: Callable, **kwargs):
            register_cli_command(name, handler, **kwargs)

        def register_lifecycle_hook(self, event: str, handler: Callable):
            register_lifecycle_hook(event, handler)

        def register_service(self, name: str, service: Any):
            register_service(name, service)

        def register_provider(self, name: str, provider: Any):
            register_provider(name, provider)

        def register_config_schema(self, schema: dict):
            register_config_schema(schema)

        def register_command(self, name: str, handler: Callable):
            register_command(name, handler)

    api = PluginAPI()

    try:
        spec.loader.exec_module(module)

        # Call setup if plugin has it
        if hasattr(module, "plugin") and hasattr(module.plugin, "setup"):
            module.plugin.setup(api)
            _registered_plugins[plugin_name] = module.plugin
            print(f"Plugin {plugin_name}: loaded successfully")
            return True
        else:
            print(f"Plugin {plugin_name}: no setup() function found")
            return False

    except Exception as e:
        print(f"Plugin {plugin_name}: error during setup: {e}")
        return False


def load_all_plugins() -> dict[str, bool]:
    """Discover and load all available plugins."""
    results = {}
    for plugin_name in discover_plugins():
        results[plugin_name] = load_plugin(plugin_name)
    return results


def get_loaded_plugins() -> dict[str, Any]:
    """Get all loaded plugins."""
    return _registered_plugins.copy()


def get_tool_factories() -> list[Callable]:
    """Get all registered tool factories."""
    return _tool_factories.copy()


def get_hooks(hook_name: str) -> list[tuple[int, Callable]]:
    """Get all handlers for a specific hook."""
    return _hooks.get(hook_name, []).copy()


def get_http_routes() -> list[tuple[str, str, Callable]]:
    """Get all registered HTTP routes."""
    return _http_routes.copy()


def get_cli_commands() -> dict[str, Callable]:
    """Get all registered CLI commands."""
    return _cli_commands.copy()


def get_lifecycle_hooks(event: str) -> list[Callable]:
    """Get all handlers for a lifecycle event."""
    return _lifecycle_hooks.get(event, []).copy()


def get_services() -> dict[str, Any]:
    """Get all registered services."""
    return _services.copy()


def get_providers() -> dict[str, Any]:
    """Get all registered providers."""
    return _providers.copy()


# Auto-load on import
def _auto_load():
    """Auto-load plugins on module import."""
    load_all_plugins()


# Uncomment to auto-load
# _auto_load()
