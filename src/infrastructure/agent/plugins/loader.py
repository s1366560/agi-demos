"""Plugin loader for registering plugin runtime contributions."""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Protocol

from .registry import AgentPluginRegistry, PluginDiagnostic, get_plugin_registry
from .runtime_api import PluginRuntimeApi


class AgentPlugin(Protocol):
    """Protocol for plugin objects consumed by AgentPluginLoader."""

    name: str

    def setup(self, api: PluginRuntimeApi) -> None:
        """Register plugin extensions into the runtime."""


class AgentPluginLoader:
    """Loads plugins and wires their runtime registrations."""

    def __init__(self, registry: AgentPluginRegistry | None = None) -> None:
        self._registry = registry or get_plugin_registry()

    async def load_plugins(self, plugins: Iterable[AgentPlugin]) -> list[PluginDiagnostic]:
        """Load and setup plugin list, collecting diagnostics instead of failing hard."""
        diagnostics: list[PluginDiagnostic] = []
        for plugin in plugins:
            plugin_name = getattr(plugin, "name", None) or plugin.__class__.__name__
            try:
                setup_fn = plugin.setup
                api = PluginRuntimeApi(plugin_name, registry=self._registry)
                setup_result = setup_fn(api)
                if inspect.isawaitable(setup_result):
                    await setup_result
            except Exception as exc:
                # Plugin setup errors are isolated to keep the rest of plugins loadable.
                diagnostics.append(
                    PluginDiagnostic(
                        plugin_name=plugin_name,
                        code="plugin_setup_failed",
                        message=str(exc),
                        level="error",
                    )
                )
        return diagnostics
