"""Plugin discovery for built-in and entry-point based plugins."""

from __future__ import annotations

import importlib.metadata as importlib_metadata
import importlib.util
import inspect
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from .manifest import (
    PluginManifestMetadata,
    load_local_plugin_manifest,
    parse_plugin_manifest_payload,
)
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
    package: str | None = None
    version: str | None = None
    kind: str | None = None
    manifest_id: str | None = None
    manifest_path: str | None = None
    channels: tuple[str, ...] = ()
    providers: tuple[str, ...] = ()
    skills: tuple[str, ...] = ()


def discover_plugins(
    *,
    state_store: PluginStateStore | None = None,
    include_builtins: bool = True,
    include_entrypoints: bool = True,
    include_local_paths: bool = True,
    include_disabled: bool = False,
    strict_local_manifest: bool = False,
) -> tuple[list[DiscoveredPlugin], list[PluginDiagnostic]]:
    """Discover plugin instances and return diagnostics for non-fatal failures."""
    discovered: list[DiscoveredPlugin] = []
    diagnostics: list[PluginDiagnostic] = []
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
                manifest_metadata, manifest_diagnostics = load_local_plugin_manifest(
                    plugin_dir,
                    plugin_name=plugin_name,
                )
                diagnostics.extend(manifest_diagnostics)
                if strict_local_manifest and _has_manifest_errors(manifest_diagnostics):
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_manifest_strict_skip",
                            message="Skipped plugin due to invalid manifest in strict mode",
                            level="warning",
                        )
                    )
                    continue
                plugin = _load_local_plugin(plugin_dir)
                plugin_name = str(getattr(plugin, "name", plugin_dir.name))
                if manifest_metadata is not None and manifest_metadata.id != plugin_name:
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_manifest_id_mismatch",
                            message=(
                                "Manifest id does not match plugin runtime name "
                                f"('{manifest_metadata.id}' != '{plugin_name}')"
                            ),
                            level="warning",
                        )
                    )
                    if strict_local_manifest:
                        diagnostics.append(
                            PluginDiagnostic(
                                plugin_name=plugin_name,
                                code="plugin_manifest_strict_skip",
                                message="Skipped plugin due to manifest id mismatch in strict mode",
                                level="warning",
                            )
                        )
                        continue
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
                        version=manifest_metadata.version if manifest_metadata else None,
                        kind=manifest_metadata.kind if manifest_metadata else None,
                        manifest_id=manifest_metadata.id if manifest_metadata else None,
                        manifest_path=manifest_metadata.manifest_path
                        if manifest_metadata
                        else None,
                        channels=manifest_metadata.channels if manifest_metadata else (),
                        providers=manifest_metadata.providers if manifest_metadata else (),
                        skills=manifest_metadata.skills if manifest_metadata else (),
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
                manifest_metadata, manifest_diagnostics = _load_entrypoint_manifest_metadata(
                    plugin=plugin,
                    plugin_name=plugin_name,
                )
                diagnostics.extend(manifest_diagnostics)
                if manifest_metadata is not None and manifest_metadata.id != plugin_name:
                    diagnostics.append(
                        PluginDiagnostic(
                            plugin_name=plugin_name,
                            code="plugin_manifest_id_mismatch",
                            message=(
                                "Manifest id does not match plugin runtime name "
                                f"('{manifest_metadata.id}' != '{plugin_name}')"
                            ),
                            level="warning",
                        )
                    )
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
                version = (
                    manifest_metadata.version
                    if manifest_metadata and manifest_metadata.version
                    else getattr(dist, "version", None)
                )
                discovered.append(
                    DiscoveredPlugin(
                        name=plugin_name,
                        plugin=plugin,
                        source="entrypoint",
                        package=package_name,
                        version=version,
                        kind=manifest_metadata.kind if manifest_metadata else None,
                        manifest_id=manifest_metadata.id if manifest_metadata else None,
                        manifest_path=manifest_metadata.manifest_path
                        if manifest_metadata
                        else None,
                        channels=manifest_metadata.channels if manifest_metadata else (),
                        providers=manifest_metadata.providers if manifest_metadata else (),
                        skills=manifest_metadata.skills if manifest_metadata else (),
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
    state_store: PluginStateStore | None,
    include_disabled: bool,
) -> bool:
    if include_disabled or state_store is None:
        return True
    return state_store.is_enabled(plugin_name)


def _has_manifest_errors(diagnostics: Sequence[PluginDiagnostic]) -> bool:
    return any(item.code == "plugin_manifest_invalid" for item in diagnostics)


def _load_entrypoint_manifest_metadata(
    *,
    plugin: Any,
    plugin_name: str,
) -> tuple[PluginManifestMetadata | None, list[PluginDiagnostic]]:
    payload = _resolve_entrypoint_manifest_payload(plugin)
    if payload is None:
        return None, []
    return parse_plugin_manifest_payload(
        payload,
        plugin_name=plugin_name,
        source="entrypoint manifest",
    )


def _resolve_entrypoint_manifest_payload(plugin: Any) -> Any | None:
    for attr in ("plugin_manifest", "manifest"):
        payload = getattr(plugin, attr, None)
        if payload is not None:
            return payload
    get_manifest = getattr(plugin, "get_manifest", None)
    if callable(get_manifest):
        return get_manifest()
    return None


def _builtin_plugins() -> list[Any]:
    """Return built-in plugins shipped inside the core runtime."""
    return []


def _iter_local_plugin_dirs(*, state_store: PluginStateStore | None) -> list[Path]:
    """Return local plugin directories under .memstack/plugins/*/plugin.py."""
    plugin_root = _resolve_local_plugin_root(state_store=state_store)
    if plugin_root is None or not plugin_root.exists():
        return []

    local_dirs: list[Path] = []
    for path in sorted(plugin_root.iterdir(), key=lambda item: item.name):
        if not path.is_dir() or path.name.startswith("."):
            continue
        if (path / LOCAL_PLUGIN_ENTRY_FILE).exists():
            local_dirs.append(path)
    return local_dirs


def _resolve_local_plugin_root(*, state_store: PluginStateStore | None) -> Path | None:
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
