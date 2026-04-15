"""Plugin Loading System - Enables plugins to provide tools, hooks, HTTP routes, etc.

This module provides the infrastructure for loading and managing plugins.
Includes comprehensive hook system for extending agent behavior.
"""

import asyncio
import importlib
import importlib.util
import json
import re
import time
import traceback
from collections.abc import Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, TypeVar

# ============================================================================
# Type Definitions
# ============================================================================

T = TypeVar('T')


class HookPhase(Enum):
    """Hook execution phases for lifecycle tracking."""
    BEFORE = "before"
    MAIN = "main"
    AFTER = "after"
    ON_ERROR = "on_error"


@dataclass
class HookContext:
    """Context object passed to hook handlers."""
    event_name: str = ""
    phase: HookPhase = HookPhase.MAIN
    data: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    start_time: float = field(default_factory=time.time)
    
    def add_error(self, error: Exception, handler_name: str = "") -> None:
        """Add an error to the context."""
        self.errors.append({
            "type": type(error).__name__,
            "message": str(error),
            "handler": handler_name,
            "timestamp": time.time()
        })
    
    def to_dict(self) -> dict:
        """Convert context to dictionary."""
        return {
            "event_name": self.event_name,
            "phase": self.phase.value,
            "data": self.data,
            "errors": self.errors,
            "metadata": self.metadata
        }


@dataclass 
class HookResult:
    """Result of hook execution."""
    success: bool = True
    value: Any = None
    error: str | None = None
    handler_name: str = ""
    execution_time_ms: float = 0.0
    
    def to_dict(self) -> dict:
        return {
            "success": self.success,
            "value": self.value,
            "error": self.error,
            "handler": self.handler_name,
            "execution_time_ms": self.execution_time_ms
        }


# ============================================================================
# Plugin Registry
# ============================================================================

_registered_plugins: dict[str, Any] = {}
_tool_factories: list[Callable] = []
_hooks: dict[str, list[tuple[int, Callable]]] = {}
_hook_metadata: dict[str, dict[int, dict]] = {}
_http_routes: list[tuple[str, str, Callable]] = []
_cli_commands: dict[str, Callable] = {}
_lifecycle_hooks: dict[str, list[Callable]] = {}
_services: dict[str, Any] = {}
_providers: dict[str, Any] = {}
_hook_stats: dict[str, dict] = {}


# ============================================================================
# Registration Functions
# ============================================================================

def register_tool_factory(factory: Callable[[Any], dict[str, Any]]) -> None:
    """Register a tool factory function."""
    _tool_factories.append(factory)


def register_hook(
    hook_name: str, 
    handler: Callable, 
    priority: int = 50,
    description: str = "",
    tags: list[str] = None,
    **kwargs
) -> None:
    """Register a hook handler.

    Args:
        hook_name: Name of the hook (e.g., 'before_tool_execute')
        handler: Function to call (sync or async)
        priority: Lower values run first (default: 50)
        description: Optional description of what the hook does
        tags: Optional tags for categorization
    """
    if hook_name not in _hooks:
        _hooks[hook_name] = []
        _hook_metadata[hook_name] = {}
    
    _hooks[hook_name].append((priority, handler))
    _hooks[hook_name].sort(key=lambda x: x[0])
    
    _hook_metadata[hook_name][priority] = {
        "description": description,
        "tags": tags or [],
        "kwargs": kwargs,
        "registered_at": time.time()
    }
    
    if hook_name not in _hook_stats:
        _hook_stats[hook_name] = {
            "total_calls": 0,
            "total_errors": 0,
            "total_execution_time_ms": 0.0
        }


def unregister_hook(hook_name: str, handler: Callable = None, priority: int = None) -> int:
    """Unregister a hook handler."""
    if hook_name not in _hooks:
        return 0
    
    original_count = len(_hooks[hook_name])
    
    if handler is not None:
        _hooks[hook_name] = [(p, h) for p, h in _hooks[hook_name] if h != handler]
    elif priority is not None:
        _hooks[hook_name] = [(p, h) for p, h in _hooks[hook_name] if p != priority]
    else:
        _hooks[hook_name] = []
    
    if priority is not None and hook_name in _hook_metadata:
        _hook_metadata[hook_name].pop(priority, None)
    
    return original_count - len(_hooks[hook_name])


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
    pass


def register_command(name: str, handler: Callable) -> None:
    """Register a named command."""
    _cli_commands[name] = handler


# ============================================================================
# Hook Execution Functions
# ============================================================================

async def run_hook(
    hook_name: str, 
    context: HookContext | dict | None = None,
    stop_on_error: bool = False,
    collect_results: bool = True
) -> list[HookResult]:
    """Run all handlers for a hook.
    
    Args:
        hook_name: Name of the hook to execute
        context: Context object or dict to pass to handlers
        stop_on_error: If True, stop execution on first error
        collect_results: If True, collect and return all results
        
    Returns:
        List of HookResult objects for each handler
    """
    results: list[HookResult] = []
    handlers = get_hooks(hook_name)
    
    if context is None:
        ctx = HookContext(event_name=hook_name)
    elif isinstance(context, dict):
        ctx = HookContext(event_name=hook_name, data=context)
    else:
        ctx = context
        ctx.event_name = hook_name
    
    if hook_name in _hook_stats:
        _hook_stats[hook_name]["total_calls"] += 1
    
    for priority, handler in handlers:
        start_time = time.perf_counter()
        result = HookResult(handler_name=getattr(handler, '__name__', str(handler)))
        
        try:
            if asyncio.iscoroutinefunction(handler):
                result.value = await handler(ctx)
            else:
                result.value = handler(ctx)
            result.success = True
        except Exception as e:
            result.success = False
            result.error = str(e)
            ctx.add_error(e, result.handler_name)
            if hook_name in _hook_stats:
                _hook_stats[hook_name]["total_errors"] += 1
        
        result.execution_time_ms = (time.perf_counter() - start_time) * 1000
        if hook_name in _hook_stats:
            _hook_stats[hook_name]["total_execution_time_ms"] += result.execution_time_ms
        
        if collect_results:
            results.append(result)
        
        if stop_on_error and not result.success:
            break
    
    return results


def run_hook_sync(
    hook_name: str, 
    context: HookContext | dict | None = None,
    stop_on_error: bool = False,
    collect_results: bool = True
) -> list[HookResult]:
    """Synchronous wrapper for run_hook."""
    return asyncio.run(run_hook(hook_name, context, stop_on_error, collect_results))


async def run_lifecycle_hook(event: str) -> list[HookResult]:
    """Run lifecycle hooks for an event."""
    results: list[HookResult] = []
    
    for handler in get_lifecycle_hooks(event):
        start_time = time.perf_counter()
        result = HookResult(handler_name=getattr(handler, '__name__', str(handler)))
        
        try:
            if asyncio.iscoroutinefunction(handler):
                await handler()
            else:
                handler()
            result.success = True
        except Exception as e:
            result.success = False
            result.error = str(e)
        finally:
            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
        
        results.append(result)
    
    return results


def run_lifecycle_hook_sync(event: str) -> list[HookResult]:
    """Synchronous wrapper for run_lifecycle_hook."""
    return asyncio.run(run_lifecycle_hook(event))


# ============================================================================
# Plugin Discovery & Loading
# ============================================================================

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
    """Load a plugin by name."""
    plugin_dir = _PLUGINS_DIR / plugin_name
    plugin_json = plugin_dir / "memstack.plugin.json"

    if not plugin_json.exists():
        print(f"Plugin {plugin_name}: memstack.plugin.json not found")
        return False

    with open(plugin_json) as f:
        config = json.load(f)

    entry_point = config.get("entry", "plugin.py")
    plugin_file = plugin_dir / entry_point

    if not plugin_file.exists():
        print(f"Plugin {plugin_name}: entry point {entry_point} not found")
        return False

    module_name = f"plugins.{plugin_name}.plugin"
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        print(f"Plugin {plugin_name}: failed to load module spec")
        return False

    module = importlib.util.module_from_spec(spec)

    class PluginAPI:
        """API object passed to plugin setup()"""

        def register_tool_factory(self, factory: Callable):
            register_tool_factory(factory)

        def register_hook(self, name: str, handler: Callable, priority: int = 50, **kwargs):
            register_hook(name, handler, priority, **kwargs)

        def unregister_hook(self, name: str, handler: Callable = None, priority: int = None):
            return unregister_hook(name, handler, priority)

        def register_http_route(self, method: str, path: str, handler: Callable, **kwargs):
            register_http_route(method, path, handler, **kwargs)

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

        @property
        def hooks(self):
            return get_hook_stats()
        
        @property
        def loaded_plugins(self):
            return list(_registered_plugins.keys())

    api = PluginAPI()

    try:
        spec.loader.exec_module(module)

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
        traceback.print_exc()
        return False


def load_all_plugins() -> dict[str, bool]:
    """Discover and load all available plugins."""
    results = {}
    for plugin_name in discover_plugins():
        results[plugin_name] = load_plugin(plugin_name)
    return results


def unload_plugin(plugin_name: str) -> bool:
    """Unload a plugin and clean up its hooks."""
    if plugin_name not in _registered_plugins:
        return False
    
    run_lifecycle_hook_sync("on_unload")
    del _registered_plugins[plugin_name]
    return True


# ============================================================================
# Getter Functions
# ============================================================================

def get_loaded_plugins() -> dict[str, Any]:
    """Get all loaded plugins."""
    return _registered_plugins.copy()


def get_tool_factories() -> list[Callable]:
    """Get all registered tool factories."""
    return _tool_factories.copy()


def get_hooks(hook_name: str) -> list[tuple[int, Callable]]:
    """Get all handlers for a specific hook."""
    return _hooks.get(hook_name, []).copy()


def get_hook_count(hook_name: str = None) -> int | dict[str, int]:
    """Get hook count."""
    if hook_name is not None:
        return len(_hooks.get(hook_name, []))
    return {name: len(hooks) for name, hooks in _hooks.items()}


def get_hook_metadata(hook_name: str = None) -> dict:
    """Get metadata for hooks."""
    if hook_name is not None:
        return _hook_metadata.get(hook_name, {})
    return _hook_metadata.copy()


def get_hook_stats(hook_name: str = None) -> dict:
    """Get execution statistics for hooks."""
    if hook_name is not None:
        stats = _hook_stats.get(hook_name, {
            "total_calls": 0,
            "total_errors": 0,
            "total_execution_time_ms": 0.0
        })
        if stats["total_calls"] > 0:
            stats["avg_execution_time_ms"] = stats["total_execution_time_ms"] / stats["total_calls"]
        return stats
    return _hook_stats.copy()


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


def get_all_hooks() -> dict[str, list[tuple[int, Callable]]]:
    """Get all registered hooks."""
    return {name: hooks.copy() for name, hooks in _hooks.items()}


# ============================================================================
# Utility Functions
# ============================================================================

def clear_hooks(hook_name: str = None) -> int:
    """Clear hooks."""
    if hook_name is not None:
        count = len(_hooks.get(hook_name, []))
        if hook_name in _hooks:
            _hooks[hook_name] = []
        return count
    else:
        total = sum(len(h) for h in _hooks.values())
        _hooks.clear()
        _hook_metadata.clear()
        _hook_stats.clear()
        return total


def clear_lifecycle_hooks(event: str = None) -> int:
    """Clear lifecycle hooks."""
    if event is not None:
        count = len(_lifecycle_hooks.get(event, []))
        if event in _lifecycle_hooks:
            _lifecycle_hooks[event] = []
        return count
    else:
        total = sum(len(h) for h in _lifecycle_hooks.values())
        _lifecycle_hooks.clear()
        return total


def reset_stats(hook_name: str = None) -> None:
    """Reset hook execution statistics."""
    if hook_name is not None:
        if hook_name in _hook_stats:
            _hook_stats[hook_name] = {
                "total_calls": 0,
                "total_errors": 0,
                "total_execution_time_ms": 0.0
            }
    else:
        for name in _hook_stats:
            _hook_stats[name] = {
                "total_calls": 0,
                "total_errors": 0,
                "total_execution_time_ms": 0.0
            }


def validate_hook_name(name: str) -> bool:
    """Validate a hook name format."""
    if not name or len(name) > 256:
        return False
    return bool(re.match(r'^[\w\-\.]+$', name))
