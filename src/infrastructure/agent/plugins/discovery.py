"""Plugin discovery for built-in and entry-point based plugins."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import importlib.util
import inspect
import logging
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, List, Optional, Sequence

from .registry import PluginDiagnostic
from .state_store import PluginStateStore

PLUGIN_ENTRYPOINT_GROUP = "memstack.agent_plugins"
LOCAL_PLUGIN_ENTRY_FILE = "plugin.py"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DiscoveredPlugin:
    """Resolved plugin instance with source metadata."""

    name: str
    plugin: Any
    source: str
    package: Optional[str] = None
    version: Optional[str] = None


def discover_plugins(
    *,
    state_store: Optional[PluginStateStore] = None,
    include_builtins: bool = True,
    include_entrypoints: bool = True,
    include_local_paths: bool = True,
    include_disabled: bool = False,
) -> tuple[List[DiscoveredPlugin], List[PluginDiagnostic]]:
    """Discover plugin instances and return diagnostics for non-fatal failures."""
    discovered: List[DiscoveredPlugin] = []
    diagnostics: List[PluginDiagnostic] = []
    seen_names: set[str] = set()

    if include_builtins:
        for plugin in _builtin_plugins():
            plugin_name = getattr(plugin, "name", plugin.__class__.__name__)
            if not _is_enabled(
                plugin_name, state_store=state_store, include_disabled=include_disabled
            ):
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_disabled",
                        message=f"Skipped disabled plugin: {plugin_name}",
                        level="info",
                    )
                )
                continue
            discovered.append(
                DiscoveredPlugin(
                    name=plugin_name,
                    plugin=plugin,
                    source="builtin",
                )
            )
            seen_names.add(plugin_name)

    if include_local_paths:
        for plugin_dir in _iter_local_plugin_dirs(state_store=state_store):
            plugin_name = plugin_dir.name
            try:
                plugin = _load_local_plugin(plugin_dir)
                plugin_name = str(getattr(plugin, "name", plugin_dir.name))
                if plugin_name in seen_names:
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_name_conflict",
                            message=f"Skipped duplicate plugin name: {plugin_name}",
                        )
                    )
                    continue
                if not _is_enabled(
                    plugin_name, state_store=state_store, include_disabled=include_disabled
                ):
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_disabled",
                            message=f"Skipped disabled plugin: {plugin_name}",
                            level="info",
                        )
                    )
                    continue

                discovered.append(
                    DiscoveredPlugin(
                        name=plugin_name,
                        plugin=plugin,
                        source="local",
                    )
                )
                seen_names.add(plugin_name)
            except ImportError as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_import_failed",
                        message=str(exc),
                        level="warning",
                    )
                )
            except (AttributeError, TypeError) as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_invalid_structure",
                        message=str(exc),
                        level="error",
                    )
                )
            except Exception as exc:
                logger.error(
                    "Unexpected local plugin discovery failure for %s",
                    plugin_name,
                    exc_info=True,
                )
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_discovery_failed",
                        message=f"Unexpected error: {exc}",
                        level="error",
                    )
                )

    if include_entrypoints:
        for entry_point in _iter_entry_points(PLUGIN_ENTRYPOINT_GROUP):
            plugin_name = entry_point.name
            try:
                loaded = entry_point.load()
                plugin = _coerce_plugin_instance(loaded)
                plugin_name = str(getattr(plugin, "name", entry_point.name))
                if plugin_name in seen_names:
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_name_conflict",
                            message=f"Skipped duplicate plugin name: {plugin_name}",
                        )
                    )
                    continue
                if not _is_enabled(
                    plugin_name, state_store=state_store, include_disabled=include_disabled
                ):
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_disabled",
                            message=f"Skipped disabled plugin: {plugin_name}",
                            level="info",
                        )
                    )
                    continue

                dist = getattr(entry_point, "dist", None)
                package_name = getattr(dist, "name", None)
                version = getattr(dist, "version", None)
                discovered.append(
                    DiscoveredPlugin(
                        name=plugin_name,
                        plugin=plugin,
                        source="entrypoint",
                        package=package_name,
                        version=version,
                    )
                )
                seen_names.add(plugin_name)
            except ImportError as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_import_failed",
                        message=str(exc),
                        level="warning",
                    )
                )
            except (AttributeError, TypeError) as exc:
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_invalid_structure",
                        message=str(exc),
                        level="error",
                    )
                )
            except Exception as exc:
                logger.error(
                    "Unexpected plugin discovery failure for %s",
                    plugin_name,
                    exc_info=True,
                )
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_discovery_failed",
                        message=f"Unexpected error: {exc}",
                        level="error",
                    )
                )

    return discovered, diagnostics


def _iter_entry_points(group: str) -> Sequence[Any]:
    entry_points = importlib_metadata.entry_points()
    if hasattr(entry_points, "select"):
        return list(entry_points.select(group=group))
    return list(entry_points.get(group, []))


def _coerce_plugin_instance(candidate: Any) -> Any:
    if inspect.isclass(candidate) or (callable(candidate) and not hasattr(candidate, "setup")):
        candidate = candidate()

    if not hasattr(candidate, "setup"):
        raise TypeError("Plugin entrypoint must provide setup(api)")
    return candidate


def _is_enabled(
    plugin_name: str,
    *,
    state_store: Optional[PluginStateStore],
    include_disabled: bool,
) -> bool:
    if include_disabled or state_store is None:
        return True
    return state_store.is_enabled(plugin_name)


def _builtin_plugins() -> List[Any]:
    """Return built-in plugins shipped inside the core runtime."""
    return []


def _iter_local_plugin_dirs(*, state_store: Optional[PluginStateStore]) -> List[Path]:
    """Return local plugin directories under .memstack/plugins/*/plugin.py."""
    plugin_root = _resolve_local_plugin_root(state_store=state_store)
    if plugin_root is None or not plugin_root.exists():
        return []

    local_dirs: List[Path] = []
    for path in sorted(plugin_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / LOCAL_PLUGIN_ENTRY_FILE).exists():
            local_dirs.append(path)
    return local_dirs


def _resolve_local_plugin_root(*, state_store: Optional[PluginStateStore]) -> Optional[Path]:
    """Resolve local plugin root path from state store context."""
    if state_store is None:
        return None
    return state_store.state_path.parent


def _load_local_plugin(plugin_dir: Path) -> Any:
    """Load one local plugin from .memstack/plugins/<name>/plugin.py."""
    plugin_file = plugin_dir / LOCAL_PLUGIN_ENTRY_FILE
    if not plugin_file.exists():
        raise ImportError(f"Missing local plugin entry file: {plugin_file}")

    module_name = f"memstack_local_plugin_{plugin_dir.name.replace('-', '_')}"
    module = _load_module_from_path(module_name=module_name, file_path=plugin_file)
    candidate = _resolve_local_plugin_candidate(module)
    return _coerce_plugin_instance(candidate)


def _load_module_from_path(*, module_name: str, file_path: Path) -> ModuleType:
    """Load a Python module from file path."""
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot create module spec for {file_path}")

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _resolve_local_plugin_candidate(module: ModuleType) -> Any:
    """Resolve plugin candidate exported by local module."""
    exported = getattr(module, "plugin", None)
    if exported is not None:
        return exported

    exported = getattr(module, "Plugin", None)
    if exported is not None:
        return exported

    for candidate in vars(module).values():
        if inspect.isclass(candidate) and hasattr(candidate, "setup"):
            return candidate

    raise TypeError(
        "Local plugin module must expose 'plugin', 'Plugin', or a class with setup(api)"
    )
