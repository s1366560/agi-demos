"""Bridge from the platform capability kernel to the legacy agent registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from src.domain.model.plugins import PluginManifest
from src.infrastructure.agent.plugins.registry import AgentPluginRegistry

from .builtin_manifests import (
    memory_runtime_manifest,
    sisyphus_runtime_manifest,
    skill_evolution_manifest,
    workspace_runtime_manifest,
)
from .context import CapabilityRegistry, PluginContext, PluginScopeContext
from .llm_adapters import (
    LlmAdapterFactory,
    LlmAdapterProviderRegistry,
    RoutedLlmAdapterProvider,
)
from .profile import ProfileSnapshot

Disposable = Callable[[], None]


@dataclass(frozen=True)
class LegacyCapability:
    """Opaque implementation marker for capability inventory parity."""

    plugin_id: str
    capability: str


@dataclass
class BuiltinPluginRegistration:
    """One reversible legacy registration made through the platform kernel."""

    manifest: PluginManifest
    context: PluginContext
    dispose_legacy: Callable[[], object]

    def dispose(self) -> None:
        """Dispose kernel capabilities first, then legacy registrations."""
        self.context.close()
        _ = self.dispose_legacy()


def register_builtin_kernel_plugins(
    capability_registry: CapabilityRegistry,
    legacy_registry: AgentPluginRegistry,
    *,
    include_memory: bool = False,
    include_skill_evolution: bool = False,
    scope: PluginScopeContext | None = None,
) -> Disposable:
    """Register trusted builtins through both registries and return a disposer."""
    registrations: list[BuiltinPluginRegistration] = []

    def activate(manifest: PluginManifest, legacy_register: Disposable) -> None:
        context = PluginContext(
            capability_registry,
            manifest,
            scope=scope,
        )
        for capability in manifest.provides:
            _ = context.register_capability(
                capability.kind,
                capability.id,
                LegacyCapability(plugin_id=manifest.id, capability=capability.contract),
            )
        legacy_register()
        registrations.append(
            BuiltinPluginRegistration(
                manifest=manifest,
                context=context,
                dispose_legacy=_dispose_legacy_plugin(legacy_registry, manifest.id),
            )
        )

    from src.infrastructure.agent.plugins.memory_plugin import (
        register_builtin_memory_plugin,
    )
    from src.infrastructure.agent.plugins.skill_evolution.plugin import (
        register_builtin_skill_evolution_plugin,
    )
    from src.infrastructure.agent.sisyphus.runtime_plugin import (
        register_builtin_sisyphus_plugin,
    )
    from src.infrastructure.agent.workspace.runtime_plugin import (
        register_builtin_workspace_plugin,
    )

    activate(
        workspace_runtime_manifest(),
        lambda: register_builtin_workspace_plugin(legacy_registry),
    )
    activate(
        sisyphus_runtime_manifest(),
        lambda: register_builtin_sisyphus_plugin(legacy_registry),
    )
    if include_memory:
        activate(
            memory_runtime_manifest(),
            lambda: register_builtin_memory_plugin(legacy_registry),
        )
    if include_skill_evolution:
        from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

        activate(
            skill_evolution_manifest(),
            lambda: register_builtin_skill_evolution_plugin(legacy_registry).setup(
                PluginRuntimeApi(skill_evolution_manifest().id, registry=legacy_registry)
            ),
        )

    def dispose() -> None:
        for registration in reversed(registrations):
            registration.dispose()
        registrations.clear()

    return dispose


def _dispose_legacy_plugin(
    legacy_registry: AgentPluginRegistry,
    plugin_id: str,
) -> Callable[[], list[str]]:
    def dispose() -> list[str]:
        return legacy_registry.unregister_plugin(plugin_id)

    return dispose


def activate_profile_snapshot(
    snapshot: ProfileSnapshot,
    capability_registry: CapabilityRegistry,
    *,
    adapter_registry: LlmAdapterProviderRegistry | None = None,
    llm_adapter_factory: LlmAdapterFactory | None = None,
) -> Disposable:
    """Activate every capability declared by a canonical profile snapshot.

    This is the Python data-plane activation path. It does not import code or
    resolve secrets; typed host factories supply implementations in later phases.
    """
    contexts: list[PluginContext] = []
    adapter_disposers: list[Disposable] = []
    for row in snapshot.rows:
        context = PluginContext(
            capability_registry,
            row.manifest,
            config=row.config,
        )
        llm_providers: dict[str, RoutedLlmAdapterProvider] = {}
        if adapter_registry is not None:
            for capability in row.manifest.provides:
                if capability.kind.value != "llm_provider":
                    continue
                if (
                    row.manifest.runtime.value != "python-trusted"
                    or row.manifest.trust.value
                    not in {
                        "builtin",
                        "signed",
                    }
                ):
                    raise ValueError("LLM adapter providers require a trusted python runtime")
                provider = RoutedLlmAdapterProvider(factory=llm_adapter_factory)
                adapter_disposers.append(
                    adapter_registry.register(
                        capability.id,
                        provider,
                        owner=row.manifest.id,
                    )
                )
                llm_providers[capability.id] = provider
        for capability in row.manifest.provides:
            implementation = llm_providers.get(
                capability.id,
                LegacyCapability(
                    plugin_id=row.manifest.id,
                    capability=capability.contract,
                ),
            )
            _ = context.register_capability(
                capability.kind,
                capability.id,
                implementation,
            )
        contexts.append(context)

    def dispose() -> None:
        for adapter_dispose in reversed(adapter_disposers):
            adapter_dispose()
        adapter_disposers.clear()
        for context in reversed(contexts):
            context.close()
        contexts.clear()

    return dispose


def register_plugin_activation(
    capability_registry: CapabilityRegistry,
    legacy_registry: AgentPluginRegistry,
    manifest: PluginManifest,
    legacy_setup: Callable[[object], object],
    *,
    config: dict[str, Any] | None = None,
    scope: PluginScopeContext | None = None,
) -> Disposable:
    """Activate one manifest-bearing plugin against both registry generations."""
    from src.infrastructure.agent.plugins.runtime_api import PluginRuntimeApi

    context = PluginContext(
        capability_registry,
        manifest,
        config=config,
        scope=scope,
    )
    for capability in manifest.provides:
        _ = context.register_capability(
            capability.kind,
            capability.id,
            LegacyCapability(plugin_id=manifest.id, capability=capability.contract),
        )
    _ = legacy_setup(PluginRuntimeApi(manifest.id, registry=legacy_registry))

    def dispose() -> None:
        context.close()
        _ = legacy_registry.unregister_plugin(manifest.id)

    return dispose
