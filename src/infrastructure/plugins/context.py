"""Reversible, plugin-scoped capability registration."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from src.domain.model.plugins import (
    CapabilityKind,
    PluginManifest,
    PluginScope,
    PluginScopeContext,
)

Disposable = Callable[[], None]

__all__ = [
    "CapabilityConflictError",
    "CapabilityRecord",
    "CapabilityRegistry",
    "Disposable",
    "PluginContext",
    "PluginScopeContext",
]


@dataclass(frozen=True)
class CapabilityRecord:
    """One registered implementation and its owning manifest."""

    plugin_id: str
    kind: CapabilityKind
    capability_id: str
    contract: str
    implementation: object
    scope: PluginScope
    permissions: tuple[str, ...]


class CapabilityConflictError(RuntimeError):
    """Raised when two active plugins claim the same capability key."""


class CapabilityRegistry:
    """Thread-safe registry of reversible plugin capabilities.

    Subsystems retain typed Service Definitions while this object owns cross-cutting
    plugin ownership, conflict detection, lookup, and deterministic snapshots.
    """

    def __init__(self) -> None:
        self._capabilities: dict[tuple[str, str], CapabilityRecord] = {}
        self._plugin_capabilities: dict[str, set[tuple[str, str]]] = {}
        self._contracts: dict[str, tuple[str, str]] = {}
        self._lock = threading.RLock()

    def register(
        self,
        manifest: PluginManifest,
        kind: CapabilityKind,
        capability_id: str,
        implementation: object,
        *,
        scope: PluginScope | None = None,
        namespace: bool = True,
    ) -> Disposable:
        """Register one manifest-declared capability and return its disposer."""
        declared = next(
            (item for item in manifest.provides if item.kind == kind and item.id == capability_id),
            None,
        )
        if declared is None:
            raise ValueError(f"plugin {manifest.id} does not declare {kind.value}:{capability_id}")

        key = _capability_key(manifest, kind, capability_id, namespace=namespace)
        with self._lock:
            existing = self._capabilities.get(key)
            if existing is not None:
                raise CapabilityConflictError(
                    f"capability {kind.value}:{capability_id} is already owned by "
                    f"{existing.plugin_id}; refusing registration from {manifest.id}"
                )
            owned_contract = _owned_contract(declared.contract, manifest.id)
            existing_contract_key = self._contracts.get(owned_contract)
            if existing_contract_key is not None:
                existing_record = self._capabilities[existing_contract_key]
                raise CapabilityConflictError(
                    f"contract {declared.contract} is already owned by {existing_record.plugin_id}"
                )
            record = CapabilityRecord(
                plugin_id=manifest.id,
                kind=kind,
                capability_id=capability_id,
                contract=declared.contract,
                implementation=implementation,
                scope=scope or manifest.activation.default_scope,
                permissions=declared.permissions,
            )
            self._capabilities[key] = record
            self._plugin_capabilities.setdefault(manifest.id, set()).add(key)
            self._contracts[owned_contract] = key

        def dispose() -> None:
            self._remove(manifest.id, key)

        return dispose

    def unregister_plugin(self, plugin_id: str) -> tuple[tuple[str, str], ...]:
        """Remove every capability currently owned by one plugin."""
        with self._lock:
            keys = tuple(sorted(self._plugin_capabilities.get(plugin_id, set())))
        for key in keys:
            self._remove(plugin_id, key)
        return keys

    def get(
        self,
        kind: CapabilityKind,
        capability_id: str,
        *,
        plugin_id: str | None = None,
    ) -> CapabilityRecord | None:
        """Return one active capability record."""
        with self._lock:
            if plugin_id is None:
                return self._capabilities.get((kind.value, capability_id))
            return self._capabilities.get((f"{kind.value}:{plugin_id}", capability_id))

    def get_by_contract(self, contract: str) -> CapabilityRecord | None:
        """Return the active capability implementing a required contract."""
        with self._lock:
            matches = [
                record for record in self._capabilities.values() if record.contract == contract
            ]
            if len(matches) > 1:
                raise CapabilityConflictError(
                    f"contract {contract} has {len(matches)} active implementations"
                )
            return matches[0] if matches else None

    def list_capabilities(self, plugin_id: str | None = None) -> tuple[CapabilityRecord, ...]:
        """Return a deterministic capability inventory."""
        with self._lock:
            return tuple(
                self._capabilities[key]
                for key in sorted(self._capabilities)
                if plugin_id is None or self._capabilities[key].plugin_id == plugin_id
            )

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a JSON-compatible deterministic inventory snapshot."""
        return [
            {
                "plugin_id": record.plugin_id,
                "kind": record.kind.value,
                "id": record.capability_id,
                "contract": record.contract,
                "scope": record.scope.value,
                "permissions": list(record.permissions),
            }
            for record in self.list_capabilities()
        ]

    def _remove(self, plugin_id: str, key: tuple[str, str]) -> None:
        with self._lock:
            record = self._capabilities.get(key)
            if record is None or record.plugin_id != plugin_id:
                return
            _ = self._capabilities.pop(key, None)
            owned_contract = _owned_contract(record.contract, plugin_id)
            if self._contracts.get(owned_contract) == key:
                del self._contracts[owned_contract]
            owned = self._plugin_capabilities.get(plugin_id)
            if owned is not None:
                owned.discard(key)
                if not owned:
                    _ = self._plugin_capabilities.pop(plugin_id, None)


def _capability_key(
    manifest: PluginManifest,
    kind: CapabilityKind,
    capability_id: str,
    *,
    namespace: bool,
) -> tuple[str, str]:
    if not namespace:
        return kind.value, capability_id
    return f"{kind.value}:{manifest.id}", capability_id


def _owned_contract(contract: str, plugin_id: str) -> str:
    return f"{contract}@{plugin_id}"


class PluginContext:
    """Scoped API handed to one plugin activation.

    Registrations made through a context are reversible even if a caller forgets to
    retain a disposer. Secret values are intentionally absent: plugins receive
    authorized references and the host resolves them at an execution boundary.
    """

    def __init__(
        self,
        registry: CapabilityRegistry,
        manifest: PluginManifest,
        *,
        config: Mapping[str, Any] | None = None,
        scope: PluginScopeContext | None = None,
        secret_grants: Mapping[str, str] | None = None,
    ) -> None:
        self.registry = registry
        self.manifest = manifest
        self.config = MappingProxyType(dict(config or {}))
        self.scope = scope or PluginScopeContext()
        self.secret_grants = MappingProxyType(dict(secret_grants or {}))
        self.logger = logging.getLogger(f"memstack.plugins.{manifest.id}").getChild("kernel")
        self._disposers: list[Disposable] = []
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return whether this activation has already been disposed."""
        return self._closed

    def register_capability(
        self,
        kind: CapabilityKind,
        capability_id: str,
        implementation: object,
        *,
        scope: PluginScope | None = None,
    ) -> Disposable:
        """Register a declared implementation and track its disposer."""
        self._ensure_open()
        dispose = self.registry.register(
            self.manifest,
            kind,
            capability_id,
            implementation,
            scope=scope,
        )
        self._disposers.append(dispose)
        return dispose

    def on(self, event_name: str, handler: object) -> Disposable:
        """Register a hook capability for one event."""
        return self.register_capability(CapabilityKind.HOOK, event_name, handler)

    def register_tool(self, tool_id: str, implementation: object) -> Disposable:
        """Register a tool capability."""
        return self.register_capability(CapabilityKind.TOOL, tool_id, implementation)

    def register_llm_provider(
        self,
        provider_id: str,
        implementation: object,
    ) -> Disposable:
        """Register an LLM provider capability."""
        return self.register_capability(CapabilityKind.LLM_PROVIDER, provider_id, implementation)

    def secret_ref(self, name: str) -> str:
        """Return an authorized secret reference without exposing its value."""
        authorized = self.secret_grants.get(name)
        if authorized is None:
            raise PermissionError(f"plugin {self.manifest.id} is not granted secret {name}")
        return authorized

    def close(self) -> None:
        """Dispose registrations in reverse acquisition order."""
        self._closed = True
        while self._disposers:
            dispose = self._disposers.pop()
            try:
                dispose()
            except Exception:
                self.logger.warning("Plugin capability disposal failed", exc_info=True)

    def _ensure_open(self) -> None:
        if self._closed:
            raise RuntimeError(f"plugin context for {self.manifest.id} is closed")
