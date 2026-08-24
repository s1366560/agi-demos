"""Resolve Agent Pool authority from an immutable V2 generation boundary."""

from __future__ import annotations

from collections.abc import Callable
from importlib import import_module
from typing import cast

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.agent_pool_runtime import (
    AGENT_POOL_RUNTIME_SERVICE_V2,
    AgentPoolRuntimeServiceV2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeGenerationV2

from .manager import AgentPoolManager

_ROOT_SCOPE_V2 = ScopeV2(kind=ScopeKindV2.ROOT)


def agent_pool_runtime_service_v2_from_current_generation() -> AgentPoolRuntimeServiceV2:
    """Resolve the service owned by the generation pinned to this operation."""
    current_generation_v2 = cast(
        "Callable[[], RuntimeGenerationV2]",
        import_module("src.infrastructure.plugins.v2.boundary").current_generation_v2,
    )

    runtime = current_generation_v2().resolve(
        AGENT_POOL_RUNTIME_SERVICE_V2,
        _ROOT_SCOPE_V2,
        version="1.0.0",
    )
    if not isinstance(runtime, AgentPoolRuntimeServiceV2):
        raise TypeError("pinned generation has an invalid Agent Pool runtime service")
    return runtime


def agent_pool_manager_v2_from_current_generation() -> AgentPoolManager:
    """Return the exact manager exposed by the pinned runtime service."""
    return agent_pool_runtime_service_v2_from_current_generation().manager


__all__ = [
    "agent_pool_manager_v2_from_current_generation",
    "agent_pool_runtime_service_v2_from_current_generation",
]
