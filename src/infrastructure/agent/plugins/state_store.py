"""Persistent state store for plugin runtime enable/disable metadata."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
from typing import Any

_DEFAULT_STATE: dict[str, Any] = {"plugins": {}, "tenants": {}}


class PluginStateStore:
    """Manage plugin runtime state persisted under .memstack/plugins/state.json."""

    def __init__(self, base_path: Path | None = None) -> None:
        root = base_path or Path.cwd()
        self._state_path = root / ".memstack" / "plugins" / "state.json"
        self._lock = RLock()

    @property
    def state_path(self) -> Path:
        """Return the plugin state file path."""
        return self._state_path

    def list_plugins(self, *, tenant_id: str | None = None) -> dict[str, dict[str, Any]]:
        """Return all persisted plugin states keyed by plugin name."""
        state = self._read_state()
        plugins = self._get_scope_plugins(state, tenant_id=tenant_id)
        if not isinstance(plugins, dict):
            return {}
        return {
            str(name): dict(payload)
            for name, payload in plugins.items()
            if isinstance(name, str) and isinstance(payload, dict)
        }

    def get_plugin(self, plugin_name: str, *, tenant_id: str | None = None) -> dict[str, Any]:
        """Get persisted state for one plugin."""
        global_state = self.list_plugins().get(plugin_name, {})
        if not isinstance(global_state, dict):
            global_state = {}

        if not tenant_id:
            return dict(global_state)

        tenant_state = self.list_plugins(tenant_id=tenant_id).get(plugin_name)
        if not isinstance(tenant_state, dict):
            return dict(global_state)

        merged = dict(global_state)
        merged.update(tenant_state)
        return merged

    def is_enabled(self, plugin_name: str, *, tenant_id: str | None = None) -> bool:
        """Check if a plugin is enabled (defaults to True when unset)."""
        plugin_state = self.get_plugin(plugin_name, tenant_id=tenant_id)
        enabled = plugin_state.get("enabled")
        if enabled is None:
            return True
        return bool(enabled)

    def set_plugin_enabled(
        self,
        plugin_name: str,
        enabled: bool,
        *,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Persist plugin enabled status."""
        return self.update_plugin(plugin_name, enabled=enabled, tenant_id=tenant_id)

    def update_plugin(  # noqa: PLR0913
        self,
        plugin_name: str,
        *,
        enabled: bool | None = None,
        source: str | None = None,
        package: str | None = None,
        version: str | None = None,
        requirement: str | None = None,
        kind: str | None = None,
        manifest_id: str | None = None,
        channels: list[str] | None = None,
        providers: list[str] | None = None,
        skills: list[str] | None = None,
        tenant_id: str | None = None,
    ) -> dict[str, Any]:
        """Create or update plugin metadata entry."""
        if not plugin_name:
            raise ValueError("plugin_name is required")

        with self._lock:
            state = self._read_state()
            plugins = self._get_scope_plugins(state, tenant_id=tenant_id, create_if_missing=True)

            current = dict(plugins.get(plugin_name, {}))
            if enabled is not None:
                current["enabled"] = bool(enabled)
            if source is not None:
                current["source"] = source
            if package is not None:
                current["package"] = package
            if version is not None:
                current["version"] = version
            if requirement is not None:
                current["requirement"] = requirement
            if kind is not None:
                current["kind"] = kind
            if manifest_id is not None:
                current["manifest_id"] = manifest_id
            if channels is not None:
                current["channels"] = _normalize_string_list(channels)
            if providers is not None:
                current["providers"] = _normalize_string_list(providers)
            if skills is not None:
                current["skills"] = _normalize_string_list(skills)
            current["updated_at"] = datetime.now(UTC).isoformat()
            plugins[plugin_name] = current
            self._write_state(state)
            return dict(current)

    def remove_plugin(self, plugin_name: str, *, tenant_id: str | None = None) -> None:
        """Remove a plugin state record."""
        with self._lock:
            state = self._read_state()
            plugins = self._get_scope_plugins(state, tenant_id=tenant_id)
            if isinstance(plugins, dict) and plugin_name in plugins:
                plugins.pop(plugin_name, None)
                self._write_state(state)

    def remove_plugin_everywhere(self, plugin_name: str) -> None:
        """Remove plugin state from global and tenant-scoped state."""
        with self._lock:
            state = self._read_state()
            changed = False

            global_plugins = self._get_scope_plugins(state)
            if isinstance(global_plugins, dict) and plugin_name in global_plugins:
                global_plugins.pop(plugin_name, None)
                changed = True

            tenants = state.get("tenants")
            if isinstance(tenants, dict):
                for tenant_state in tenants.values():
                    if not isinstance(tenant_state, dict):
                        continue
                    tenant_plugins = tenant_state.get("plugins")
                    if isinstance(tenant_plugins, dict) and plugin_name in tenant_plugins:
                        tenant_plugins.pop(plugin_name, None)
                        changed = True

            if changed:
                self._write_state(state)

    def _read_state(self) -> dict[str, Any]:
        if not self._state_path.exists():
            return deepcopy(_DEFAULT_STATE)
        try:
            raw = self._state_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            return deepcopy(_DEFAULT_STATE)
        return deepcopy(_DEFAULT_STATE)

    def _write_state(self, state: dict[str, Any]) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(state, ensure_ascii=False, indent=2, sort_keys=True)
        self._state_path.write_text(payload, encoding="utf-8")

    def _get_scope_plugins(
        self,
        state: dict[str, Any],
        *,
        tenant_id: str | None = None,
        create_if_missing: bool = False,
    ) -> dict[str, Any]:
        if tenant_id:
            tenants = state.get("tenants")
            if not isinstance(tenants, dict):
                if not create_if_missing:
                    return {}
                tenants = {}
                state["tenants"] = tenants

            tenant_state = tenants.get(tenant_id)
            if not isinstance(tenant_state, dict):
                if not create_if_missing:
                    return {}
                tenant_state = {}
                tenants[tenant_id] = tenant_state

            plugins = tenant_state.get("plugins")
            if not isinstance(plugins, dict):
                if not create_if_missing:
                    return {}
                plugins = {}
                tenant_state["plugins"] = plugins
            return plugins

        plugins = state.get("plugins")
        if not isinstance(plugins, dict):
            if not create_if_missing:
                return {}
            plugins = {}
            state["plugins"] = plugins
        return plugins


def _normalize_string_list(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    normalized: list[str] = []
    for item in value:
        if isinstance(item, str):
            clean = item.strip()
            if clean:
                normalized.append(clean)
    return normalized
