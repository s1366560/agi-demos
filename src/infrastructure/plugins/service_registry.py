"""Cordis-style service repository for the platform composition root.

Phase P1 of the full-pluginization roadmap: the hardcoded DI container is
migrated onto a service registry where a service claims a stable key
(``tools``, ``llm``, ``sessions``, ...), dependents declare required keys via
``inject``, and every registration is a reversible effect. Activation order
is derived from declared dependencies (topological), never from manual boot
sequencing, and ``close()`` unwinds effects in reverse acquisition order.

This module is additive: nothing here mutates the legacy DI container. The
container's factories migrate onto declarations incrementally while the old
accessor facade stays as the compatibility shim.
"""

from __future__ import annotations

import inspect
import logging
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)

ServiceFactory = Callable[["ServiceContext"], Any]
Disposable = Callable[[], None]

__all__ = [
    "Disposable",
    "ServiceConflictError",
    "ServiceContext",
    "ServiceDeclaration",
    "ServiceDependencyError",
    "ServiceFactory",
    "ServiceRegistry",
]


class ServiceConflictError(RuntimeError):
    """Raised when a key is claimed twice without explicit replacement."""


class ServiceDependencyError(RuntimeError):
    """Raised for missing dependencies or dependency cycles."""


@dataclass(frozen=True)
class ServiceDeclaration:
    """A lazy service whose activation waits for its declared dependencies."""

    key: str
    factory: ServiceFactory
    inject: tuple[str, ...] = ()
    owner: str | None = None


@dataclass
class _ServiceEntry:
    """One active service and its teardown effect."""

    key: str
    instance: object
    owner: str | None
    dispose: Disposable | None


class ServiceContext:
    """Resolution view handed to one factory.

    Only keys named in the declaration's ``inject`` are visible, so service
    requirements are explicit and auditable instead of ambient.
    """

    def __init__(self, registry: ServiceRegistry, declaration: ServiceDeclaration) -> None:
        super().__init__()
        self._registry = registry
        self._declaration = declaration

    @property
    def key(self) -> str:
        """Return the key this activation is producing."""
        return self._declaration.key

    def get(self, key: str) -> object:
        """Return an injected dependency instance."""
        if key not in self._declaration.inject:
            raise PermissionError(
                f"service {self._declaration.key} did not declare inject for {key}"
            )
        return self._registry.get(key)


class ServiceRegistry:
    """Key-addressed service repository with reversible, ordered activation."""

    def __init__(self) -> None:
        self._entries: dict[str, _ServiceEntry] = {}
        self._declarations: dict[str, ServiceDeclaration] = {}
        self._activation_order: list[str] = []
        self._lock = threading.RLock()

    # -- eager registration -------------------------------------------------

    def register(
        self,
        key: str,
        instance: object,
        *,
        owner: str | None = None,
        dispose: Disposable | None = None,
        replace: bool = False,
    ) -> Disposable:
        """Claim a key with an already-built instance and return its disposer."""
        normalized = _normalize_key(key)
        with self._lock:
            self._evict_for_write(normalized, replace=replace)
            self._entries[normalized] = _ServiceEntry(
                key=normalized,
                instance=instance,
                owner=owner,
                dispose=dispose,
            )
            self._activation_order.append(normalized)

        def dispose_entry() -> None:
            self.unregister(normalized)

        return dispose_entry

    def unregister(self, key: str) -> bool:
        """Remove one active service, running its teardown effect."""
        normalized = _normalize_key(key)
        with self._lock:
            entry = self._entries.pop(normalized, None)
            if entry is None:
                return False
            if normalized in self._activation_order:
                self._activation_order.remove(normalized)
        if entry.dispose is not None:
            entry.dispose()
        return True

    # -- lookup ---------------------------------------------------------------

    def get(self, key: str) -> object:
        """Return the active instance for a key."""
        normalized = _normalize_key(key)
        with self._lock:
            entry = self._entries.get(normalized)
        if entry is None:
            raise KeyError(f"no active service for key {normalized}")
        return entry.instance

    def has(self, key: str) -> bool:
        """Return whether a key currently has an active instance."""
        with self._lock:
            return _normalize_key(key) in self._entries

    def keys(self) -> tuple[str, ...]:
        """Return active service keys in activation order."""
        with self._lock:
            return tuple(self._activation_order)

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a deterministic inventory for diagnostics and dumps."""
        with self._lock:
            return [
                {"key": key, "owner": self._entries[key].owner} for key in self._activation_order
            ]

    # -- declarative, dependency-ordered activation ---------------------------

    def declare(self, declaration: ServiceDeclaration, *, replace: bool = False) -> None:
        """Register a lazy service declaration for later activation."""
        normalized = _normalize_key(declaration.key)
        with self._lock:
            if normalized in self._declarations and not replace:
                raise ServiceConflictError(
                    f"service {normalized} already declared; pass replace=True"
                )
            self._declarations[normalized] = ServiceDeclaration(
                key=normalized,
                factory=declaration.factory,
                inject=tuple(dict.fromkeys(declaration.inject)),
                owner=declaration.owner,
            )

    async def activate_all(self) -> tuple[str, ...]:
        """Activate pending declarations in dependency order.

        Each factory runs once its ``inject`` keys are all active. Missing
        dependencies and cycles raise :class:`ServiceDependencyError` naming
        the offenders; any activation failure unwinds the services this call
        activated, in reverse order, before re-raising.
        """
        with self._lock:
            pending = {
                key: declaration
                for key, declaration in self._declarations.items()
                if key not in self._entries
            }
        activated: list[str] = []
        try:
            while pending:
                progressed = False
                for key in sorted(pending):
                    declaration = pending[key]
                    if not self._dependencies_active(declaration):
                        continue
                    await self._activate(declaration)
                    activated.append(key)
                    del pending[key]
                    progressed = True
                if not progressed:
                    raise _dependency_error(pending, self._entries)
        except Exception:
            for key in reversed(activated):
                self.unregister(key)
            raise
        return tuple(activated)

    async def _activate(self, declaration: ServiceDeclaration) -> None:
        """Run one factory and register its instance."""
        context = ServiceContext(self, declaration)
        instance = declaration.factory(context)
        if inspect.isawaitable(instance):
            instance = await instance
        if instance is None:
            raise ServiceDependencyError(f"service factory for {declaration.key} returned None")
        dispose: Disposable | None = None
        close_method = getattr(instance, "close", None)
        if callable(close_method):

            def _dispose_instance() -> None:
                close_method()

            dispose = _dispose_instance

        _ = self.register(
            declaration.key,
            instance,
            owner=declaration.owner,
            dispose=dispose,
        )
        with self._lock:
            _ = self._declarations.pop(declaration.key, None)

    def _dependencies_active(self, declaration: ServiceDeclaration) -> bool:
        """Return whether every injected key is active."""
        with self._lock:
            return all(dep in self._entries for dep in declaration.inject)

    # -- teardown ---------------------------------------------------------------

    async def close(self) -> None:
        """Dispose every active service in reverse activation order."""
        while True:
            with self._lock:
                if not self._activation_order:
                    return
                key = self._activation_order[-1]
            self.unregister(key)

    def _evict_for_write(self, key: str, *, replace: bool) -> None:
        existing = self._entries.pop(key, None)
        if existing is not None:
            if not replace:
                self._entries[key] = existing
                raise ServiceConflictError(f"service {key} already active; pass replace=True")
            self._activation_order.remove(key)
            if existing.dispose is not None:
                existing.dispose()


def _normalize_key(key: str) -> str:
    normalized = (key or "").strip()
    if not normalized:
        raise ValueError("service key must be a non-empty string")
    return normalized


def _dependency_error(
    pending: Mapping[str, ServiceDeclaration],
    entries: Mapping[str, _ServiceEntry],
) -> ServiceDependencyError:
    """Build an actionable dependency error for an unresolvable pending set."""
    missing: dict[str, list[str]] = {}
    cycle_candidates: list[str] = []
    for key, declaration in pending.items():
        absent = [dep for dep in declaration.inject if dep not in entries and dep not in pending]
        if absent:
            missing[key] = absent
        else:
            cycle_candidates.append(key)
    parts: list[str] = []
    if missing:
        details = ", ".join(
            f"{key} requires {sorted(deps)}" for key, deps in sorted(missing.items())
        )
        parts.append(f"missing dependencies: {details}")
    if cycle_candidates:
        parts.append(f"dependency cycle among: {sorted(cycle_candidates)}")
    return ServiceDependencyError("; ".join(parts))
