"""Activate ROOT background consumers only through an installed, admitted generation."""

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .boundary import current_process_generation_host_v2
from .runtime import OperationContextV2, RuntimeGenerationV2, RuntimeV2Error
from .runtime_host import PlatformPluginRuntimeHostV2
from .skill_evolution_runtime import (
    SKILL_EVOLUTION_RUNTIME_MODULE_V2,
    SKILL_EVOLUTION_RUNTIME_SERVICE_V2,
    SkillEvolutionActivationProtocolV2,
)


async def activate_root_background_services_v2(generation: RuntimeGenerationV2) -> None:
    """Use the host's short publication lease; do not retain it in background tasks."""
    host = current_process_generation_host_v2()
    if not isinstance(host, PlatformPluginRuntimeHostV2) or host.manager.current is not generation:
        raise RuntimeV2Error(
            "process_generation_activation_mismatch",
            "background activation requires the installed process generation",
        )
    if not any(
        entry.enabled and entry.module_ref == SKILL_EVOLUTION_RUNTIME_MODULE_V2
        for entry in generation.snapshot.entries
    ):
        return
    async with OperationContextV2(
        generation=generation,
        operation_id=f"root-background-activation:{generation.descriptor.generation}",
        scope=ScopeV2(kind=ScopeKindV2.ROOT),
    ) as operation:
        service = operation.require(SKILL_EVOLUTION_RUNTIME_SERVICE_V2)
        if not isinstance(service, SkillEvolutionActivationProtocolV2):
            raise RuntimeV2Error(
                "invalid_skill_evolution_activation",
                "published Skill Evolution service cannot activate its generation",
            )
        await service.activate(operation)
