"""Builtin frontend plugin slot registry."""

from __future__ import annotations

from collections.abc import Callable

from src.domain.model.plugins import PluginRuntimeKind, PluginTrust
from src.domain.ports.plugins import UiSlotDefinition, UiSlotKind

Disposable = Callable[[], None]


class UiSlotRegistrationError(RuntimeError):
    """Raised when a frontend plugin slot is unsafe."""


class UiSlotRegistry:
    """Track signed builtin frontend modules without loading their code."""

    def __init__(self) -> None:
        self._slots: dict[tuple[UiSlotKind, str], UiSlotDefinition] = {}
        self._plugin_slots: dict[str, set[tuple[UiSlotKind, str]]] = {}

    def register(
        self,
        definition: UiSlotDefinition,
        *,
        trust: PluginTrust,
        runtime: PluginRuntimeKind,
    ) -> Disposable:
        """Register one allowlisted slot and return its disposer."""
        if trust not in {PluginTrust.BUILTIN, PluginTrust.SIGNED}:
            raise UiSlotRegistrationError("external frontend modules are not enabled")
        if runtime != PluginRuntimeKind.FRONTEND:
            raise UiSlotRegistrationError("UI slots require frontend runtime")
        if not definition.sandbox:
            raise UiSlotRegistrationError("UI renderers must run in a sandbox")
        if not definition.permission.startswith("ui."):
            raise UiSlotRegistrationError("UI slot permission must start with ui.")
        if definition.module_ref and not definition.module_ref.startswith("builtin:"):
            raise UiSlotRegistrationError("only builtin frontend module refs are allowed")

        key = definition.slot, definition.id
        if key in self._slots:
            raise UiSlotRegistrationError(f"UI slot already registered: {definition.id}")
        self._slots[key] = definition
        self._plugin_slots.setdefault(definition.plugin_id, set()).add(key)

        def dispose() -> None:
            if self._slots.pop(key, None) is not None:
                owned = self._plugin_slots.get(definition.plugin_id)
                if owned is not None:
                    owned.discard(key)
                    if not owned:
                        self._plugin_slots.pop(definition.plugin_id, None)

        return dispose

    def list(
        self,
        slot: UiSlotKind | None = None,
    ) -> tuple[UiSlotDefinition, ...]:
        """Return deterministic visible slot definitions."""
        return tuple(
            self._slots[key] for key in sorted(self._slots) if slot is None or key[0] == slot
        )
