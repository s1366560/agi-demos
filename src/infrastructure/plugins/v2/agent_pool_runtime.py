"""Generation-owned Agent Pool runtime Provider primitive."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

if TYPE_CHECKING:
    from src.infrastructure.agent.pool.integration.session_adapter import (
        PooledAgentSessionAdapter,
    )
    from src.infrastructure.agent.pool.manager import AgentPoolManager

AGENT_POOL_RUNTIME_MODULE_V2 = "builtin://memstack/agent/pool-runtime"
AGENT_POOL_RUNTIME_SERVICE_V2 = "service:agent.pool-runtime"

_CONFIG_KEYS_V2 = frozenset(
    {
        "strategy",
        "max_total_instances",
        "health_check_interval_seconds",
        "cleanup_interval_seconds",
        "enable_resource_isolation",
        "enable_health_monitoring",
        "enable_auto_classification",
        "enable_prewarming",
        "prewarm_on_startup",
        "fallback_on_pool_error",
        "enable_metrics",
    }
)


@dataclass(frozen=True, kw_only=True)
class AgentPoolRuntimeServiceV2:
    """Pool adapter and manager owned by exactly one plugin generation."""

    adapter: PooledAgentSessionAdapter

    @property
    def manager(self) -> AgentPoolManager:
        """Return the started manager exposed to pinned HTTP consumers."""
        from src.infrastructure.agent.pool.manager import AgentPoolManager

        manager = self.adapter.pool_manager
        if not isinstance(manager, AgentPoolManager):
            raise RuntimeV2Error(
                "agent_pool_manager_unavailable",
                "generation-owned Agent Pool adapter has no started manager",
            )
        return manager

    async def start(self) -> None:
        """Start the complete generation-owned adapter before publication."""
        await self.adapter.start()
        _ = self.manager

    async def dispose(self) -> None:
        """Stop background work and all instances before Fiber release."""
        await self.adapter.stop()


type AgentPoolRuntimeFactoryV2 = Callable[
    [Mapping[str, Any]],
    AgentPoolRuntimeServiceV2 | Awaitable[AgentPoolRuntimeServiceV2],
]


def default_agent_pool_runtime_config_v2(
    *,
    health_check_interval_seconds: int = 30,
) -> dict[str, object]:
    """Build the explicit deployment projection stored in every snapshot."""
    return {
        "strategy": "pooled-session-adapter",
        "max_total_instances": 100,
        "health_check_interval_seconds": health_check_interval_seconds,
        "cleanup_interval_seconds": 300,
        "enable_resource_isolation": True,
        "enable_health_monitoring": True,
        "enable_auto_classification": True,
        "enable_prewarming": True,
        "prewarm_on_startup": False,
        "fallback_on_pool_error": False,
        "enable_metrics": True,
    }


def create_agent_pool_runtime_service_v2(
    config: Mapping[str, Any],
) -> AgentPoolRuntimeServiceV2:
    """Construct the in-process implementation from validated Profile config."""
    from src.infrastructure.agent.pool.config import PoolConfig
    from src.infrastructure.agent.pool.integration.session_adapter import (
        AdapterConfig,
        PooledAgentSessionAdapter,
    )

    _validate_runtime_config_v2(config)
    pool_config = PoolConfig(
        max_total_instances=int(config["max_total_instances"]),
        health_check_interval_seconds=int(config["health_check_interval_seconds"]),
        cleanup_interval_seconds=int(config["cleanup_interval_seconds"]),
    )
    adapter_config = AdapterConfig(
        enable_pool_management=True,
        enable_resource_isolation=bool(config["enable_resource_isolation"]),
        enable_health_monitoring=bool(config["enable_health_monitoring"]),
        enable_auto_classification=bool(config["enable_auto_classification"]),
        fallback_on_pool_error=bool(config["fallback_on_pool_error"]),
        enable_prewarming=bool(config["enable_prewarming"]),
        prewarm_on_startup=bool(config["prewarm_on_startup"]),
        enable_metrics=bool(config["enable_metrics"]),
    )
    return AgentPoolRuntimeServiceV2(
        adapter=PooledAgentSessionAdapter(
            pool_config=pool_config,
            adapter_config=adapter_config,
        )
    )


def agent_pool_runtime_definition_v2(
    agent_pool_runtime_factory: AgentPoolRuntimeFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Build the reversible Agent Pool Provider definition."""
    factory = agent_pool_runtime_factory or create_agent_pool_runtime_service_v2

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        _validate_runtime_config_v2(config)
        runtime: AgentPoolRuntimeServiceV2 | None = None

        async def acquire() -> Callable[[], Awaitable[None]]:
            nonlocal runtime
            candidate = factory(dict(config))
            if inspect.isawaitable(candidate):
                candidate = await candidate
            if not isinstance(candidate, AgentPoolRuntimeServiceV2):
                raise RuntimeV2Error(
                    "invalid_agent_pool_runtime_factory_result",
                    "Agent Pool runtime factory returned an invalid service",
                )
            try:
                await candidate.start()
            except Exception:
                await candidate.dispose()
                raise
            runtime = candidate
            return candidate.dispose

        await context.effect(acquire, label="agent-pool-runtime")
        if runtime is None:
            raise RuntimeV2Error(
                "agent_pool_runtime_acquisition_failed",
                "Agent Pool runtime acquisition completed without a service",
            )
        _ = context.provide(
            AGENT_POOL_RUNTIME_SERVICE_V2,
            runtime,
            label="agent-pool-runtime-provider",
        )

    return PluginDefinitionV2(
        module_ref=AGENT_POOL_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_POOL_RUNTIME_MODULE_V2),
        apply=apply,
    )


def _validate_runtime_config_v2(config: Mapping[str, Any]) -> None:
    if frozenset(config) != _CONFIG_KEYS_V2:
        raise ValueError("Agent Pool runtime config does not match its public contract")
    if config.get("strategy") != "pooled-session-adapter":
        raise ValueError("Agent Pool runtime requires strategy pooled-session-adapter")


__all__ = [
    "AGENT_POOL_RUNTIME_MODULE_V2",
    "AGENT_POOL_RUNTIME_SERVICE_V2",
    "AgentPoolRuntimeFactoryV2",
    "AgentPoolRuntimeServiceV2",
    "agent_pool_runtime_definition_v2",
    "create_agent_pool_runtime_service_v2",
    "default_agent_pool_runtime_config_v2",
]
