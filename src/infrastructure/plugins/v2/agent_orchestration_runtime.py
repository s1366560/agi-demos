"""Generation-owned Agent orchestration Provider and lifecycle manager."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.agent.orchestration.orchestrator import (
    AgentOrchestrator,
    SessionTurnExecutionRequest,
    SpawnExecutionRequest,
)
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

from .runtime import (
    ContextV2,
    EffectResultV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_ORCHESTRATION_RUNTIME_MODULE_V2 = "builtin://memstack/agent/orchestration-runtime"
AGENT_ORCHESTRATION_RUNTIME_SERVICE_V2 = "service:agent.orchestration-runtime"
AGENT_ORCHESTRATION_SUBAGENT_RUNS_INJECT_V2 = "subagent_runs"

type AgentSpawnExecutorV2 = Callable[[SpawnExecutionRequest], Awaitable[None]]
type AgentSessionTurnExecutorV2 = Callable[[SessionTurnExecutionRequest], Awaitable[None]]
type AgentOrchestratorDisposerV2 = Callable[[], None | Awaitable[None]]


@dataclass(frozen=True, kw_only=True)
class AgentOrchestratorResourceV2:
    """One bound orchestrator and the disposer for its owned resources."""

    orchestrator: AgentOrchestrator
    dispose: AgentOrchestratorDisposerV2


type AgentOrchestratorFactoryV2 = Callable[
    [SubAgentRunRegistry, AgentSpawnExecutorV2, AgentSessionTurnExecutorV2],
    AgentOrchestratorResourceV2 | Awaitable[AgentOrchestratorResourceV2],
]


@runtime_checkable
class AgentOrchestrationRuntimeProtocolV2(Protocol):
    """Bind one host owner to an orchestrator within this generation."""

    async def bind(
        self,
        *,
        owner: object,
        spawn_executor: AgentSpawnExecutorV2,
        session_turn_executor: AgentSessionTurnExecutorV2,
    ) -> AgentOrchestrator: ...

    async def close(self) -> None: ...


@dataclass(frozen=True, kw_only=True)
class _OwnerBindingV2:
    owner: object
    resource: AgentOrchestratorResourceV2


class AgentOrchestrationRuntimeV2:
    """Cache host-specific orchestrators and release them with the generation."""

    def __init__(  # pyright: ignore[reportMissingSuperCall]
        self,
        *,
        run_registry: SubAgentRunRegistry,
        factory: AgentOrchestratorFactoryV2 | None = None,
    ) -> None:
        self._run_registry = run_registry
        self._factory = factory or create_agent_orchestrator_resource_v2
        self._bindings: dict[int, _OwnerBindingV2] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    async def bind(
        self,
        *,
        owner: object,
        spawn_executor: AgentSpawnExecutorV2,
        session_turn_executor: AgentSessionTurnExecutorV2,
    ) -> AgentOrchestrator:
        """Return the stable orchestrator owned by this generation and host owner."""
        async with self._lock:
            if self._closed:
                raise RuntimeV2Error(
                    "disposed_agent_orchestration_runtime",
                    "Agent orchestration runtime is already disposed",
                )
            owner_key = id(owner)
            binding = self._bindings.get(owner_key)
            if binding is not None:
                if binding.owner is not owner:
                    raise RuntimeV2Error(
                        "agent_orchestration_owner_conflict",
                        "Agent orchestration owner identity was reused unexpectedly",
                    )
                return binding.resource.orchestrator

            resource = self._factory(
                self._run_registry,
                spawn_executor,
                session_turn_executor,
            )
            if inspect.isawaitable(resource):
                resource = await resource
            if not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
                resource, AgentOrchestratorResourceV2
            ) or not isinstance(  # pyright: ignore[reportUnnecessaryIsInstance]
                resource.orchestrator,
                AgentOrchestrator,
            ):
                raise RuntimeV2Error(
                    "invalid_agent_orchestrator_factory_result",
                    "Agent orchestrator factory returned an invalid resource",
                )
            self._bindings[owner_key] = _OwnerBindingV2(owner=owner, resource=resource)
            return resource.orchestrator

    async def close(self) -> None:
        """Dispose bound resources in reverse creation order exactly once."""
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            resources = tuple(binding.resource for binding in self._bindings.values())
            self._bindings.clear()

        errors: list[str] = []
        for resource in reversed(resources):
            try:
                result = resource.dispose()
                if inspect.isawaitable(result):
                    await result
            except Exception as exc:
                errors.append(f"{type(exc).__name__}: {exc}")
        if errors:
            raise RuntimeV2Error(
                "agent_orchestration_dispose_failed",
                "; ".join(errors),
            )


async def create_agent_orchestrator_resource_v2(
    run_registry: SubAgentRunRegistry,
    spawn_executor: AgentSpawnExecutorV2,
    session_turn_executor: AgentSessionTurnExecutorV2,
) -> AgentOrchestratorResourceV2:
    """Create the default production orchestrator and its DB-session disposer."""
    from src.infrastructure.adapters.secondary.messaging.redis_agent_message_bus import (
        RedisAgentMessageBusAdapter,
    )
    from src.infrastructure.adapters.secondary.persistence.database import async_session_factory
    from src.infrastructure.adapters.secondary.persistence.sql_agent_registry import (
        SqlAgentRegistryRepository,
    )
    from src.infrastructure.agent.orchestration.session_registry import AgentSessionRegistry
    from src.infrastructure.agent.orchestration.spawn_manager import SpawnManager
    from src.infrastructure.agent.state.agent_worker_state import get_redis_client

    db_session = async_session_factory()
    try:
        redis = await get_redis_client()
        session_registry = AgentSessionRegistry()
        orchestrator = AgentOrchestrator(
            agent_registry=SqlAgentRegistryRepository(db_session),
            session_registry=session_registry,
            spawn_manager=SpawnManager(
                session_registry=session_registry,
                run_registry=run_registry,
            ),
            message_bus=RedisAgentMessageBusAdapter(redis),
            db_session=db_session,
            spawn_executor=spawn_executor,
            session_turn_executor=session_turn_executor,
        )
    except Exception:
        await db_session.close()
        raise

    async def dispose() -> None:
        await db_session.close()

    return AgentOrchestratorResourceV2(
        orchestrator=orchestrator,
        dispose=dispose,
    )


def agent_orchestration_runtime_definition_v2(
    factory: AgentOrchestratorFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Provide one reversible orchestration manager per generation."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "generation-owned":
            raise ValueError("Agent orchestration runtime requires strategy generation-owned")
        run_registry = context.require(AGENT_ORCHESTRATION_SUBAGENT_RUNS_INJECT_V2)
        if not isinstance(run_registry, SubAgentRunRegistry):
            raise RuntimeV2Error(
                "invalid_agent_orchestration_subagent_registry",
                "Agent orchestration runtime received an invalid SubAgent registry",
            )
        runtime = AgentOrchestrationRuntimeV2(
            run_registry=run_registry,
            factory=factory,
        )
        _ = context.provide(
            AGENT_ORCHESTRATION_RUNTIME_SERVICE_V2,
            runtime,
            label="agent-orchestration-runtime",
        )
        return runtime.close

    return PluginDefinitionV2(
        module_ref=AGENT_ORCHESTRATION_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_ORCHESTRATION_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AGENT_ORCHESTRATION_RUNTIME_MODULE_V2",
    "AGENT_ORCHESTRATION_RUNTIME_SERVICE_V2",
    "AGENT_ORCHESTRATION_SUBAGENT_RUNS_INJECT_V2",
    "AgentOrchestrationRuntimeProtocolV2",
    "AgentOrchestrationRuntimeV2",
    "AgentOrchestratorFactoryV2",
    "AgentOrchestratorResourceV2",
    "AgentSessionTurnExecutorV2",
    "AgentSpawnExecutorV2",
    "agent_orchestration_runtime_definition_v2",
    "create_agent_orchestrator_resource_v2",
]
