"""Structural Agent tool capability counts from one pinned V2 generation."""

from __future__ import annotations

from dataclasses import dataclass

from src.domain.model.plugins.generated_v2 import (
    DataPlaneTargetV2,
    PluginModuleV2,
    ScopeKindV2,
    ScopeV2,
)

from .channel_adapters import (
    CHANNEL_ADAPTER_RESOLVER_SERVICE_V2,
    ChannelAdapterResolverProtocolV2,
)
from .runtime import RuntimeGenerationV2
from .runtime_context import FiberPhaseV2, RuntimeV2Error
from .tool_set import TOOL_CONTRIBUTION_MODULE_V2

_ROOT_SCOPE_V2 = ScopeV2(kind=ScopeKindV2.ROOT)


@dataclass(frozen=True, kw_only=True)
class AgentToolCapabilityProjectionV2:
    """Transport-neutral structural counts for the Python Agent data plane."""

    plugins_total: int
    plugins_enabled: int
    tool_contributions: int
    channel_types: int
    hook_handlers: int
    commands: int
    services: int
    service_provider_effects: int


def project_agent_tool_capabilities_v2(
    generation: RuntimeGenerationV2,
) -> AgentToolCapabilityProjectionV2:
    """Project only declared contracts and active effects from one generation."""
    python_plugin_ids: set[str] = set()
    modules_by_identity: dict[tuple[str, str], PluginModuleV2] = {}
    for manifest in generation.snapshot.manifests:
        for module in manifest.modules:
            if DataPlaneTargetV2.PYTHON not in module.targets:
                continue
            python_plugin_ids.add(manifest.plugin_id)
            modules_by_identity[(manifest.plugin_id, module.module_ref)] = module

    active_plugin_ids: set[str] = set()
    provided_services: set[tuple[str, str]] = set()
    tool_contributions = 0
    hook_handlers = 0
    service_provider_effects = 0
    for fiber in generation.fibers:
        if fiber.phase is not FiberPhaseV2.ACTIVE:
            continue
        identity = (fiber.entry.plugin_ref, fiber.entry.module_ref)
        active_module = modules_by_identity.get(identity)
        if active_module is None:
            raise RuntimeV2Error(
                "active_fiber_contract_missing",
                f"active entry {fiber.entry.entry_id} has no Python module contract",
            )
        active_plugin_ids.add(fiber.entry.plugin_ref)
        provided = active_module.contract.services.provides
        provided_services.update((item.service, item.version) for item in provided)
        service_provider_effects += int(bool(provided))
        hook_handlers += len(active_module.contract.events.handles)
        tool_contributions += int(active_module.module_ref == TOOL_CONTRIBUTION_MODULE_V2)

    resolver = generation.resolve(CHANNEL_ADAPTER_RESOLVER_SERVICE_V2, _ROOT_SCOPE_V2)
    if not isinstance(resolver, ChannelAdapterResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_channel_adapter_resolver",
            "active generation returned an invalid channel adapter resolver",
        )

    return AgentToolCapabilityProjectionV2(
        plugins_total=len(python_plugin_ids),
        plugins_enabled=len(active_plugin_ids),
        tool_contributions=tool_contributions,
        channel_types=len(resolver.list_metadata()),
        hook_handlers=hook_handlers,
        commands=0,
        services=len(provided_services),
        service_provider_effects=service_provider_effects,
    )


__all__ = [
    "AgentToolCapabilityProjectionV2",
    "project_agent_tool_capabilities_v2",
]
