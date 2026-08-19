"""Bridge from the platform capability kernel to the legacy agent registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
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
from .profile import PluginSnapshotRow, ProfileSnapshot
from .prompt_sections import (
    NATIVE_TOOL_PROTOCOL_GUIDANCE,
    NATIVE_TOOL_PROTOCOL_SECTION_ID,
)

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
                _builtin_implementation(manifest, capability),
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


@dataclass(frozen=True)
class PreparedLlmProvider:
    """One validated provider instance shared by both registries."""

    manifest_id: str
    capability_id: str
    provider: RoutedLlmAdapterProvider


@dataclass(frozen=True)
class PreparedSnapshotActivation:
    """Pure validation result for one snapshot; no registry has been mutated."""

    snapshot: ProfileSnapshot
    llm_providers: tuple[PreparedLlmProvider, ...]


def prepare_profile_snapshot(
    snapshot: ProfileSnapshot,
    *,
    llm_adapter_factory: LlmAdapterFactory | None = None,
) -> PreparedSnapshotActivation:
    """Validate trust gates and construct provider instances without mutation."""
    providers: list[PreparedLlmProvider] = []
    for row in snapshot.rows:
        for capability in row.manifest.provides:
            if capability.kind.value != "llm_provider":
                continue
            if row.manifest.runtime.value != "python-trusted" or row.manifest.trust.value not in {
                "builtin",
                "signed",
            }:
                raise ValueError("LLM adapter providers require a trusted python runtime")
            providers.append(
                PreparedLlmProvider(
                    manifest_id=row.manifest.id,
                    capability_id=capability.id,
                    provider=RoutedLlmAdapterProvider(factory=llm_adapter_factory),
                )
            )
    return PreparedSnapshotActivation(snapshot=snapshot, llm_providers=tuple(providers))


def activate_profile_snapshot(
    snapshot: ProfileSnapshot,
    capability_registry: CapabilityRegistry,
    *,
    adapter_registry: LlmAdapterProviderRegistry | None = None,
    llm_adapter_factory: LlmAdapterFactory | None = None,
    prepared: PreparedSnapshotActivation | None = None,
) -> Disposable:
    """Activate every capability declared by a canonical profile snapshot.

    This is the Python data-plane activation path. It does not import code or
    resolve secrets; typed host factories supply implementations in later phases.

    When *prepared* is supplied, the trust-gate validation and provider
    construction from :func:`prepare_profile_snapshot` are reused, letting a
    reconciler separate validation from mutation.
    """
    if prepared is None:
        prepared = prepare_profile_snapshot(snapshot, llm_adapter_factory=llm_adapter_factory)
    if prepared.snapshot is not snapshot:
        raise ValueError("prepared activation does not match the snapshot")
    providers_by_key = {
        (provider.manifest_id, provider.capability_id): provider.provider
        for provider in prepared.llm_providers
    }
    contexts: list[PluginContext] = []
    adapter_disposers: list[Disposable] = []
    pending_context: PluginContext | None = None

    def dispose_all() -> None:
        for adapter_dispose in reversed(adapter_disposers):
            adapter_dispose()
        adapter_disposers.clear()
        for context in reversed(contexts):
            context.close()
        contexts.clear()

    try:
        for row in snapshot.rows:
            pending_context = _activate_row(
                row,
                capability_registry,
                adapter_registry=adapter_registry,
                providers_by_key=providers_by_key,
                adapter_disposers=adapter_disposers,
            )
            contexts.append(pending_context)
            pending_context = None
    except Exception:
        # A failed activation must not leak partially registered capabilities:
        # close every context created so far (including a row in progress that
        # was not yet appended) and release adapter registrations in reverse.
        if pending_context is not None:
            pending_context.close()
            pending_context = None
        dispose_all()
        raise

    return dispose_all


def _activate_row(
    row: PluginSnapshotRow,
    capability_registry: CapabilityRegistry,
    *,
    adapter_registry: LlmAdapterProviderRegistry | None,
    providers_by_key: Mapping[tuple[str, str], RoutedLlmAdapterProvider],
    adapter_disposers: list[Disposable],
) -> PluginContext:
    """Register one snapshot row's adapters and capabilities."""
    context = PluginContext(
        capability_registry,
        row.manifest,
        config=row.config,
    )
    if adapter_registry is not None:
        for capability in row.manifest.provides:
            provider = providers_by_key.get((row.manifest.id, capability.id))
            if provider is None:
                continue
            adapter_disposers.append(
                adapter_registry.register(
                    capability.id,
                    provider,
                    owner=row.manifest.id,
                )
            )
    for capability in row.manifest.provides:
        provider = providers_by_key.get((row.manifest.id, capability.id))
        implementation: object = (
            provider
            if provider is not None
            else LegacyCapability(
                plugin_id=row.manifest.id,
                capability=capability.contract,
            )
        )
        _ = context.register_capability(
            capability.kind,
            capability.id,
            implementation,
        )
    return context


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


def _builtin_implementation(manifest: PluginManifest, capability: object) -> object:
    """Resolve the live implementation for one builtin capability row.

    Prompt sections register their canonical text (the processor merges it
    into runtime guidance); everything else keeps the opaque legacy marker.
    """
    from src.domain.model.plugins import CapabilityKind, ProvidedCapability

    if isinstance(capability, ProvidedCapability) and (
        capability.kind == CapabilityKind.SYSTEM_PROMPT_SECTION
        and capability.id == NATIVE_TOOL_PROTOCOL_SECTION_ID
    ):
        return NATIVE_TOOL_PROTOCOL_GUIDANCE
    contract = getattr(capability, "contract", "")
    return LegacyCapability(plugin_id=manifest.id, capability=contract)
