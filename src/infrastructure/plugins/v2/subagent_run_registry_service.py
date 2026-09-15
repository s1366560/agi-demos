"""Generation-owned Provider seam for the shared SubAgent run registry."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from src.infrastructure.agent.subagent.production_run_registry_v2 import (
    production_subagent_run_registry_v2,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

from .runtime import ContextV2, PluginDefinitionV2, RuntimeV2Error, generated_contract_digest_v2

SUBAGENT_RUN_REGISTRY_MODULE_V2 = "builtin://memstack/agent/subagent-run-registry"
SUBAGENT_RUN_REGISTRY_SERVICE_V2 = "service:agent.subagent-run-registry"

_CONFIG_KEYS_V2 = frozenset({"strategy"})

type SubAgentRunRegistryFactoryV2 = Callable[[dict[str, Any]], SubAgentRunRegistry]


def create_subagent_run_registry_v2(config: Mapping[str, Any]) -> SubAgentRunRegistry:
    """Resolve the process-shared registry from deployment settings once per generation."""
    _validate_config_v2(config)
    return production_subagent_run_registry_v2()


def subagent_run_registry_definition_v2(
    factory: SubAgentRunRegistryFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Provide the shared registry through an explicit generation contract."""
    service_factory = factory or create_subagent_run_registry_v2

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        _validate_config_v2(config)
        registry = service_factory(dict(config))
        if not isinstance(registry, SubAgentRunRegistry):
            raise RuntimeV2Error(
                "invalid_subagent_run_registry_factory_result",
                "SubAgent run registry factory returned an invalid service",
            )
        _ = context.provide(
            SUBAGENT_RUN_REGISTRY_SERVICE_V2,
            registry,
            label="subagent-run-registry-provider",
        )

    return PluginDefinitionV2(
        module_ref=SUBAGENT_RUN_REGISTRY_MODULE_V2,
        contract_digest=generated_contract_digest_v2(SUBAGENT_RUN_REGISTRY_MODULE_V2),
        apply=apply,
    )


def _validate_config_v2(config: Mapping[str, Any]) -> None:
    if frozenset(config) != _CONFIG_KEYS_V2:
        raise ValueError("SubAgent run registry config does not match its public contract")
    if config.get("strategy") != "settings-shared":
        raise ValueError("SubAgent run registry requires strategy settings-shared")


__all__ = [
    "SUBAGENT_RUN_REGISTRY_MODULE_V2",
    "SUBAGENT_RUN_REGISTRY_SERVICE_V2",
    "SubAgentRunRegistryFactoryV2",
    "create_subagent_run_registry_v2",
    "subagent_run_registry_definition_v2",
]
