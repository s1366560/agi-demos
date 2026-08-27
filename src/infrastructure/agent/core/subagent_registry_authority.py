"""Pinned V2 authority seam for SubAgent run-registry consumers."""

from __future__ import annotations

from collections.abc import Callable

from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry
from src.infrastructure.plugins.v2.agent_worker_runtime import (
    current_agent_worker_runtime_services_v2,
)
from src.infrastructure.plugins.v2.runtime import RuntimeV2Error

type SubAgentRunRegistryResolverV2 = Callable[[], object]


def _validate_subagent_run_registry_v2(registry: object) -> SubAgentRunRegistry:
    if not isinstance(registry, SubAgentRunRegistry):
        raise RuntimeV2Error(
            "invalid_agent_subagent_run_registry",
            "Agent SubAgent runtime resolved an invalid run registry",
        )
    return registry


def require_subagent_run_registry_v2(
    resolver: SubAgentRunRegistryResolverV2,
) -> SubAgentRunRegistry:
    """Resolve and validate the registry for the current operation."""
    return _validate_subagent_run_registry_v2(resolver())


def current_agent_subagent_run_registry_v2() -> SubAgentRunRegistry:
    """Resolve the registry through the pinned generation's Worker runtime."""
    services = current_agent_worker_runtime_services_v2()
    return require_subagent_run_registry_v2(lambda: services.subagent_run_registry)


__all__ = [
    "SubAgentRunRegistryResolverV2",
    "current_agent_subagent_run_registry_v2",
    "require_subagent_run_registry_v2",
]
