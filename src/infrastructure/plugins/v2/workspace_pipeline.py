"""Generation-owned Workspace pipeline provider contributions."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final

from src.infrastructure.agent.workspace_plan import drone as drone_module

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2: Final[str] = (
    "builtin://memstack/workspace/pipeline-provider/drone"
)
WORKSPACE_DRONE_PIPELINE_PROVIDER_SERVICE_V2: Final[str] = (
    "service:workspace.pipeline-provider.drone"
)


def _apply_workspace_drone_pipeline_provider_v2(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    if config.get("provider") != "drone":
        raise ValueError("Workspace Drone pipeline provider requires provider drone")
    provider_type = getattr(drone_module, "DronePipelineProvider", None)
    if not isinstance(provider_type, type):
        raise RuntimeV2Error(
            "invalid_pipeline_provider",
            "Workspace Drone pipeline provider implementation is unavailable",
        )
    _ = context.provide(
        WORKSPACE_DRONE_PIPELINE_PROVIDER_SERVICE_V2,
        provider_type(),
        label="workspace-drone-pipeline-provider",
    )


def builtin_workspace_drone_pipeline_provider_definition_v2() -> PluginDefinitionV2:
    """Return the trusted Drone provider Definition admitted by the target catalog."""
    return PluginDefinitionV2(
        module_ref=WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2),
        apply=_apply_workspace_drone_pipeline_provider_v2,
    )


__all__ = [
    "WORKSPACE_DRONE_PIPELINE_PROVIDER_MODULE_V2",
    "WORKSPACE_DRONE_PIPELINE_PROVIDER_SERVICE_V2",
    "builtin_workspace_drone_pipeline_provider_definition_v2",
]
