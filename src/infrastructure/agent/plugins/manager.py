"""Plugin runtime manager for discovery, loading, and lifecycle operations."""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from .discovery import DiscoveredPlugin, discover_plugins
from .loader import AgentPluginLoader
from .manifest import normalize_string_list
from .registry import AgentPluginRegistry, PluginDiagnostic, get_plugin_registry
from .state_store import PluginStateStore

_REQUIREMENT_RE = re.compile(r"^\s*([A-Za-z0-9_.-]+)")
_SAFE_REQUIREMENT_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?(?:(==|>=|<=|~=|!=)[A-Za-z0-9*+!_.-]+)?$"
)
_INSTALL_TIMEOUT_SECONDS = 300.0
_UNINSTALL_TIMEOUT_SECONDS = 300.0
_MANIFEST_STRICT_ENV = "MEMSTACK_PLUGIN_MANIFEST_STRICT"
logger = logging.getLogger(__name__)


class PluginRuntimeManager:
    """Coordinate plugin discovery, activation state, and runtime loading."""

    def __init__(
        self,
        *,
        registry: Optional[AgentPluginRegistry] = None,
        state_store: Optional[PluginStateStore] = None,
        strict_local_manifest: Optional[bool] = None,
    ) -> None:
        self._registry = registry or get_plugin_registry()
        self._state_store = state_store or PluginStateStore()
        self._loader = AgentPluginLoader(registry=self._registry)
        self._lock = asyncio.Lock()
        self._loaded = False
        self._last_discovered: List[DiscoveredPlugin] = []
        self._strict_local_manifest = (
            _read_env_bool(_MANIFEST_STRICT_ENV)
            if strict_local_manifest is None
            else bool(strict_local_manifest)
        )

    async def ensure_loaded(self, *, force_reload: bool = False) -> List[PluginDiagnostic]:
        """Ensure enabled plugins are discovered and loaded into registry."""
        async with self._lock:
            if self._loaded and not force_reload:
                return []

            if force_reload:
                self._registry.clear()

            discovered, discovery_diagnostics = discover_plugins(
                state_store=self._state_store,
                strict_local_manifest=self._strict_local_manifest,
            )
            self._last_discovered = discovered

            setup_diagnostics = await self._loader.load_plugins(
                [plugin.plugin for plugin in discovered]
            )
            loaded_diagnostics = [
                PluginDiagnostic(
                    plugin_name=plugin.name,
                    code="plugin_loaded",
                    message=f"Loaded plugin from {plugin.source}",
                    level="info",
                )
                for plugin in discovered
            ]
            self._loaded = True
            return discovery_diagnostics + setup_diagnostics + loaded_diagnostics

    async def reload(self) -> List[PluginDiagnostic]:
        """Force plugin re-discovery and registry rebuild."""
        return await self.ensure_loaded(force_reload=True)

    def list_plugins(
        self,
        *,
        tenant_id: Optional[str] = None,
    ) -> tuple[List[Dict[str, Any]], List[PluginDiagnostic]]:
        """List discovered plugin metadata with enabled status."""
        discovered, diagnostics = discover_plugins(
            state_store=self._state_store,
            include_disabled=True,
            strict_local_manifest=self._strict_local_manifest,
        )
        state_map = self._state_store.list_plugins()
        tenant_state_map = self._state_store.list_plugins(tenant_id=tenant_id) if tenant_id else {}

        records: List[Dict[str, Any]] = []
        seen = set()
        for plugin in discovered:
            state_entry = dict(state_map.get(plugin.name, {}))
            if tenant_id:
                state_entry.update(tenant_state_map.get(plugin.name, {}))
            records.append(
                {
                    "name": plugin.name,
                    "source": plugin.source,
                    "package": plugin.package,
                    "version": plugin.version,
                    "kind": _coalesce_str(state_entry.get("kind"), plugin.kind),
                    "manifest_id": _coalesce_str(state_entry.get("manifest_id"), plugin.manifest_id),
                    "manifest_path": plugin.manifest_path,
                    "channels": _coalesce_string_list(
                        state_entry.get("channels"),
                        plugin.channels,
                    ),
                    "providers": _coalesce_string_list(
                        state_entry.get("providers"),
                        plugin.providers,
                    ),
                    "skills": _coalesce_string_list(
                        state_entry.get("skills"),
                        plugin.skills,
                    ),
                    "enabled": bool(state_entry.get("enabled", True)),
                    "discovered": True,
                }
            )
            seen.add(plugin.name)

        merged_state_names = set(state_map.keys()) | set(tenant_state_map.keys())
        for plugin_name in merged_state_names:
            if plugin_name in seen:
                continue
            state_entry = dict(state_map.get(plugin_name, {}))
            if tenant_id:
                state_entry.update(tenant_state_map.get(plugin_name, {}))
            records.append(
                {
                    "name": plugin_name,
                    "source": state_entry.get("source", "state"),
                    "package": state_entry.get("package"),
                    "version": state_entry.get("version"),
                    "kind": state_entry.get("kind"),
                    "manifest_id": state_entry.get("manifest_id"),
                    "manifest_path": state_entry.get("manifest_path"),
                    "channels": list(normalize_string_list(state_entry.get("channels"))),
                    "providers": list(normalize_string_list(state_entry.get("providers"))),
                    "skills": list(normalize_string_list(state_entry.get("skills"))),
                    "enabled": bool(state_entry.get("enabled", True)),
                    "discovered": False,
                }
            )

        records.sort(key=lambda item: item["name"])
        return records, diagnostics

    async def set_plugin_enabled(
        self,
        plugin_name: str,
        enabled: bool,
        *,
        tenant_id: Optional[str] = None,
    ) -> List[PluginDiagnostic]:
        """Enable or disable a plugin and reload runtime registry."""
        if tenant_id:
            self._state_store.update_plugin(plugin_name, enabled=enabled, tenant_id=tenant_id)
            return []

        previous_state = self._state_store.get_plugin(plugin_name)
        self._state_store.update_plugin(plugin_name, enabled=enabled)
        try:
            return await self.reload()
        except Exception:
            self._restore_plugin_state(plugin_name, previous_state)
            raise

    async def install_plugin(self, requirement: str) -> Dict[str, Any]:
        """Install plugin package with pip and reload runtime registry."""
        normalized_requirement = requirement.strip()
        if not normalized_requirement:
            return {
                "success": False,
                "error": "requirement is required",
            }

        validation_error = _validate_requirement(normalized_requirement)
        if validation_error:
            return {
                "success": False,
                "requirement": normalized_requirement,
                "error": validation_error,
            }

        before_plugins = {item["name"] for item in self.list_plugins()[0]}
        command = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            normalized_requirement,
        ]
        try:
            process = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                ),
                timeout=_INSTALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "requirement": normalized_requirement,
                "error": f"pip install timed out after {_INSTALL_TIMEOUT_SECONDS:.0f} seconds",
            }

        if process.returncode != 0:
            return {
                "success": False,
                "requirement": normalized_requirement,
                "command": command,
                "returncode": process.returncode,
                "stdout": _trim_output(process.stdout),
                "stderr": _trim_output(process.stderr),
            }

        diagnostics = await self.reload()
        after_plugin_records = self.list_plugins()[0]
        after_plugins = {item["name"] for item in after_plugin_records}
        new_plugins = sorted(after_plugins - before_plugins)
        requirement_name = _extract_requirement_name(normalized_requirement)
        after_by_name = {item["name"]: item for item in after_plugin_records}
        for plugin_name in new_plugins:
            record = after_by_name.get(plugin_name, {})
            self._state_store.update_plugin(
                plugin_name,
                enabled=True,
                source="entrypoint",
                package=requirement_name,
                requirement=normalized_requirement,
                kind=record.get("kind"),
                manifest_id=record.get("manifest_id"),
                channels=record.get("channels"),
                providers=record.get("providers"),
                skills=record.get("skills"),
            )

        return {
            "success": True,
            "requirement": normalized_requirement,
            "command": command,
            "stdout": _trim_output(process.stdout),
            "stderr": _trim_output(process.stderr),
            "new_plugins": new_plugins,
            "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
        }

    async def uninstall_plugin(self, plugin_name: str) -> Dict[str, Any]:
        """Uninstall plugin package by plugin name and reload runtime registry."""
        normalized_name = plugin_name.strip()
        if not normalized_name:
            return {
                "success": False,
                "error": "plugin_name is required",
            }

        plugins, _ = self.list_plugins()
        plugin_record = next((item for item in plugins if item["name"] == normalized_name), None)
        if not plugin_record:
            return {
                "success": False,
                "plugin_name": normalized_name,
                "error": "Plugin not found in runtime inventory",
            }

        package_name = plugin_record.get("package")
        if not package_name:
            return {
                "success": False,
                "plugin_name": normalized_name,
                "error": "Only package-managed plugins can be uninstalled",
            }

        command = [
            sys.executable,
            "-m",
            "pip",
            "uninstall",
            "--disable-pip-version-check",
            "--yes",
            str(package_name),
        ]
        try:
            process = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    command,
                    capture_output=True,
                    text=True,
                    check=False,
                ),
                timeout=_UNINSTALL_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            return {
                "success": False,
                "plugin_name": normalized_name,
                "package": package_name,
                "error": f"pip uninstall timed out after {_UNINSTALL_TIMEOUT_SECONDS:.0f} seconds",
            }

        if process.returncode != 0:
            return {
                "success": False,
                "plugin_name": normalized_name,
                "package": package_name,
                "command": command,
                "returncode": process.returncode,
                "stdout": _trim_output(process.stdout),
                "stderr": _trim_output(process.stderr),
            }

        diagnostics = await self.reload()
        self._state_store.remove_plugin_everywhere(normalized_name)
        return {
            "success": True,
            "plugin_name": normalized_name,
            "package": package_name,
            "command": command,
            "stdout": _trim_output(process.stdout),
            "stderr": _trim_output(process.stderr),
            "diagnostics": [_serialize_diagnostic(item) for item in diagnostics],
        }

    def _restore_plugin_state(self, plugin_name: str, previous_state: Dict[str, Any]) -> None:
        if not previous_state:
            self._state_store.remove_plugin(plugin_name)
            return

        self._state_store.remove_plugin(plugin_name)
        self._state_store.update_plugin(
            plugin_name,
            enabled=previous_state.get("enabled")
            if isinstance(previous_state.get("enabled"), bool)
            else None,
            source=previous_state.get("source"),
            package=previous_state.get("package"),
            version=previous_state.get("version"),
            requirement=previous_state.get("requirement"),
            kind=previous_state.get("kind"),
            manifest_id=previous_state.get("manifest_id"),
            channels=previous_state.get("channels"),
            providers=previous_state.get("providers"),
            skills=previous_state.get("skills"),
        )


def _trim_output(text: str, *, max_chars: int = 3000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated]"


def _extract_requirement_name(requirement: str) -> Optional[str]:
    match = _REQUIREMENT_RE.match(requirement)
    if not match:
        return None
    return match.group(1)


def _validate_requirement(requirement: str) -> Optional[str]:
    lower = requirement.lower()
    blocked_markers = ("http://", "https://", "git+", "file://", "/", "\\", ";", "&", "|", "`", "$")
    if any(marker in lower for marker in blocked_markers):
        logger.warning(
            "Blocked unsafe plugin requirement",
            extra={"requirement": requirement, "reason": "blocked_marker"},
        )
        return "Only PyPI package specifiers are allowed (URLs/paths/shell tokens are blocked)"
    if not _SAFE_REQUIREMENT_RE.fullmatch(requirement):
        logger.warning(
            "Blocked invalid plugin requirement format",
            extra={"requirement": requirement, "reason": "regex_mismatch"},
        )
        return "Invalid requirement format"
    return None


def _read_env_bool(name: str) -> bool:
    value = os.getenv(name, "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _coalesce_str(preferred: Any, fallback: Optional[str]) -> Optional[str]:
    if isinstance(preferred, str) and preferred.strip():
        return preferred.strip()
    return fallback


def _coalesce_string_list(preferred: Any, fallback: Any) -> List[str]:
    preferred_list = list(normalize_string_list(preferred))
    if preferred_list:
        return preferred_list
    return list(normalize_string_list(fallback))


def _serialize_diagnostic(diagnostic: PluginDiagnostic) -> Dict[str, Any]:
    return {
        "plugin_name": diagnostic.plugin_name,
        "code": diagnostic.code,
        "message": diagnostic.message,
        "level": diagnostic.level,
    }


_plugin_runtime_manager = PluginRuntimeManager()


def get_plugin_runtime_manager() -> PluginRuntimeManager:
    """Get global plugin runtime manager singleton."""
    return _plugin_runtime_manager
