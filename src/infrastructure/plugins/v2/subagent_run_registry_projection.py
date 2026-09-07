"""Thin projection from a pinned boundary to the SubAgent run registry."""

from __future__ import annotations

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

from .boundary import current_generation_v2
from .runtime import RuntimeV2Error
from .subagent_run_registry_service import SUBAGENT_RUN_REGISTRY_SERVICE_V2


def current_subagent_run_registry_v2() -> SubAgentRunRegistry:
    """Resolve the registry from the exact generation pinned to this operation."""
    service = current_generation_v2().resolve(
        SUBAGENT_RUN_REGISTRY_SERVICE_V2,
        ScopeV2(kind=ScopeKindV2.ROOT),
    )
    if not isinstance(service, SubAgentRunRegistry):
        raise RuntimeV2Error(
            "invalid_subagent_run_registry_service",
            "SubAgent run registry service has an invalid implementation",
        )
    return service


__all__ = ["current_subagent_run_registry_v2"]
