"""Generation-owned runtime services consumed by Agent Worker operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Protocol, cast, runtime_checkable

import redis.asyncio as redis

from src.configuration.config import get_settings
from src.domain.ports.services.graph_store_port import GraphStorePort
from src.domain.ports.services.sandbox_port import SandboxConnectionError
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.agent.canvas.manager import CanvasManager
from src.infrastructure.agent.orchestration.orchestrator import AgentOrchestrator
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

from .agent_orchestration_runtime import (
    AgentOrchestrationRuntimeProtocolV2,
    AgentSessionTurnExecutorV2,
    AgentSpawnExecutorV2,
)
from .graph_runtime import GraphRuntimeFactoryV2, GraphRuntimeServiceV2
from .redis_runtime import RedisRuntimeServiceV2
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_runtime import SandboxRuntimeServiceV2

if TYPE_CHECKING:
    from .workspace_core_runtime import WorkspaceCoreRuntimeServiceV2

AGENT_WORKER_RUNTIME_MODULE_V2 = "builtin://memstack/agent/worker-runtime"
AGENT_WORKER_RUNTIME_SERVICE_V2 = "service:agent.worker-runtime"
AGENT_WORKER_GRAPH_RUNTIME_INJECT_V2 = "graph_runtime"
AGENT_WORKER_REDIS_RUNTIME_INJECT_V2 = "redis"
AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2 = "sandbox_runtime"
AGENT_WORKER_SUBAGENT_RUNS_INJECT_V2 = "subagent_runs"
AGENT_WORKER_ORCHESTRATION_RUNTIME_INJECT_V2 = "orchestration_runtime"
AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2 = "service:operation.agent-orchestrator"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AgentWorkerRuntimeServicesV2:
    """Runtime capabilities resolved from one exact generation."""

    graph_runtime: GraphRuntimeServiceV2
    redis_runtime: RedisRuntimeServiceV2
    sandbox_adapter: MCPSandboxAdapter | None
    canvas_manager: CanvasManager
    subagent_run_registry: SubAgentRunRegistry
    orchestration_runtime: AgentOrchestrationRuntimeProtocolV2
    unavailable_code: str | None = None


@runtime_checkable
class AgentWorkerRuntimeResolverProtocolV2(Protocol):
    """Resolve Agent Worker capabilities without exposing Provider implementations."""

    def resolve(self, operation: OperationContextV2) -> AgentWorkerRuntimeServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentWorkerRuntimeResolverV2:
    """Project generation-owned sandbox state into an Agent Worker operation."""

    graph_runtime: GraphRuntimeServiceV2
    redis_runtime: RedisRuntimeServiceV2
    sandbox_runtime: SandboxRuntimeServiceV2
    canvas_manager: CanvasManager
    subagent_run_registry: SubAgentRunRegistry
    orchestration_runtime: AgentOrchestrationRuntimeProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentWorkerRuntimeServicesV2:
        _ = operation.descriptor
        sandbox_services = self.sandbox_runtime.services
        if sandbox_services is None:
            return AgentWorkerRuntimeServicesV2(
                graph_runtime=self.graph_runtime,
                redis_runtime=self.redis_runtime,
                sandbox_adapter=None,
                canvas_manager=self.canvas_manager,
                subagent_run_registry=self.subagent_run_registry,
                orchestration_runtime=self.orchestration_runtime,
                unavailable_code=(
                    self.sandbox_runtime.unavailable_code or "sandbox_runtime_unavailable"
                ),
            )
        return AgentWorkerRuntimeServicesV2(
            graph_runtime=self.graph_runtime,
            redis_runtime=self.redis_runtime,
            sandbox_adapter=sandbox_services.adapter,
            canvas_manager=self.canvas_manager,
            subagent_run_registry=self.subagent_run_registry,
            orchestration_runtime=self.orchestration_runtime,
        )


def current_agent_worker_runtime_services_v2() -> AgentWorkerRuntimeServicesV2:
    """Resolve worker services from the exact operation generation."""
    from .boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    resolver = operation.require(AGENT_WORKER_RUNTIME_SERVICE_V2)
    if not isinstance(resolver, AgentWorkerRuntimeResolverProtocolV2):
        raise RuntimeV2Error(
            "invalid_agent_worker_runtime",
            "agent worker runtime service has an invalid resolver",
        )
    services = resolver.resolve(operation)
    if not isinstance(services, AgentWorkerRuntimeServicesV2):
        raise RuntimeV2Error(
            "invalid_agent_worker_runtime",
            "agent worker runtime resolver returned invalid services",
        )
    return services


def current_agent_worker_redis_client_v2() -> redis.Redis:
    """Resolve the Redis client from the exact pinned Agent operation."""
    client = current_agent_worker_runtime_services_v2().redis_runtime.client
    if client is None:
        raise RuntimeV2Error(
            "agent_worker_redis_unavailable",
            "Agent Worker requires the generation Redis runtime",
        )
    return cast(redis.Redis, client)


def current_agent_canvas_manager_v2() -> CanvasManager:
    """Resolve the Canvas manager owned by the active V2 runtime host."""
    manager = current_agent_worker_runtime_services_v2().canvas_manager
    if not isinstance(manager, CanvasManager):
        raise RuntimeV2Error(
            "invalid_agent_canvas_runtime",
            "agent worker runtime resolved an invalid Canvas manager",
        )
    return manager


async def bind_current_agent_orchestrator_v2(
    *,
    owner: object,
    spawn_executor: AgentSpawnExecutorV2,
    session_turn_executor: AgentSessionTurnExecutorV2,
) -> AgentOrchestrator:
    """Bind and publish the exact generation's orchestrator in this operation."""
    from .boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    services = current_agent_worker_runtime_services_v2()
    orchestrator = await services.orchestration_runtime.bind(
        owner=owner,
        spawn_executor=spawn_executor,
        session_turn_executor=session_turn_executor,
    )
    try:
        existing = operation.require(AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2)
    except RuntimeV2Error as exc:
        if exc.code != "missing_service":
            raise
    else:
        if existing is not orchestrator:
            raise RuntimeV2Error(
                "agent_orchestrator_operation_conflict",
                "operation already has a different Agent orchestrator binding",
            )
        return orchestrator

    _ = operation.provide(
        AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2,
        orchestrator,
        label="operation-agent-orchestrator",
    )
    return orchestrator


def current_agent_orchestrator_v2() -> AgentOrchestrator:
    """Resolve the orchestrator pinned to the current operation and generation."""
    from .boundary import current_operation_context_v2

    operation = current_operation_context_v2()
    orchestrator = operation.require(AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2)
    if not isinstance(orchestrator, AgentOrchestrator):
        raise RuntimeV2Error(
            "invalid_operation_agent_orchestrator",
            "operation Agent orchestrator service has an invalid implementation",
        )
    return orchestrator


def agent_worker_sandbox_runtime_factory_v2() -> MCPSandboxAdapter | None:
    """Build the Agent Worker sandbox adapter owned by one V2 generation."""
    settings = get_settings()
    try:
        return MCPSandboxAdapter(
            mcp_image=settings.sandbox_default_image,
            default_timeout=settings.sandbox_timeout_seconds,
            default_memory_limit=settings.sandbox_memory_limit,
            default_cpu_limit=settings.sandbox_cpu_limit,
        )
    except SandboxConnectionError as exc:
        logger.warning(
            "Agent Worker sandbox runtime unavailable: error_type=%s",
            type(exc).__name__,
        )
        return None


def agent_worker_graph_runtime_factory_v2(
    tenant_id: str | None,
) -> GraphRuntimeFactoryV2:
    """Build a tenant-bound graph factory for one Agent data-plane generation."""

    async def factory() -> GraphStorePort:
        from src.configuration.factories import create_native_graph_adapter
        from src.infrastructure.llm.initializer import initialize_default_llm_providers

        try:
            await initialize_default_llm_providers()
        except Exception as exc:
            logger.warning(
                "Agent Worker LLM provider initialization failed before graph activation: "
                "error_type=%s",
                type(exc).__name__,
            )
        return await create_native_graph_adapter(tenant_id=tenant_id)

    return factory


async def agent_worker_redis_runtime_factory_v2() -> redis.Redis:
    """Create one Redis client owned by an Agent data-plane generation."""
    settings = get_settings()
    client: redis.Redis = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        max_connections=50,
    )
    return client


async def agent_worker_workspace_core_runtime_factory_v2() -> WorkspaceCoreRuntimeServiceV2:
    """Create and health-check Workspace Core resources for one worker generation."""
    from src.configuration.workspace_core import get_workspace_core_settings
    from src.infrastructure.adapters.primary.web.workspace_core_runtime import (
        create_workspace_core_runtime_service_v2,
    )

    return await create_workspace_core_runtime_service_v2(get_workspace_core_settings())


def agent_worker_runtime_definition_v2(
    *,
    canvas_manager: CanvasManager | None = None,
) -> PluginDefinitionV2:
    """Build the explicit Agent Worker runtime Consumer definition."""
    host_canvas_manager = canvas_manager if canvas_manager is not None else CanvasManager()

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "generation-sandbox-runtime":
            raise ValueError("agent worker runtime requires strategy generation-sandbox-runtime")
        graph_runtime = context.require(AGENT_WORKER_GRAPH_RUNTIME_INJECT_V2)
        if not isinstance(graph_runtime, GraphRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_agent_worker_graph_runtime",
                "Agent Worker graph runtime inject has an invalid implementation",
            )
        redis_runtime = context.require(AGENT_WORKER_REDIS_RUNTIME_INJECT_V2)
        if not isinstance(redis_runtime, RedisRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_agent_worker_redis_runtime",
                "Agent Worker Redis runtime inject has an invalid implementation",
            )
        sandbox_runtime = context.require(AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2)
        if not isinstance(sandbox_runtime, SandboxRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_agent_worker_sandbox_runtime",
                "Agent Worker sandbox runtime inject has an invalid implementation",
            )
        subagent_run_registry = context.require(AGENT_WORKER_SUBAGENT_RUNS_INJECT_V2)
        if not isinstance(subagent_run_registry, SubAgentRunRegistry):
            raise RuntimeV2Error(
                "invalid_agent_worker_subagent_run_registry",
                "Agent Worker SubAgent run registry inject has an invalid implementation",
            )
        orchestration_runtime = context.require(AGENT_WORKER_ORCHESTRATION_RUNTIME_INJECT_V2)
        if not isinstance(orchestration_runtime, AgentOrchestrationRuntimeProtocolV2):
            raise RuntimeV2Error(
                "invalid_agent_worker_orchestration_runtime",
                "Agent Worker orchestration runtime inject has an invalid implementation",
            )
        _ = context.provide(
            AGENT_WORKER_RUNTIME_SERVICE_V2,
            AgentWorkerRuntimeResolverV2(
                graph_runtime=graph_runtime,
                redis_runtime=redis_runtime,
                sandbox_runtime=sandbox_runtime,
                canvas_manager=host_canvas_manager,
                subagent_run_registry=subagent_run_registry,
                orchestration_runtime=orchestration_runtime,
            ),
            label="agent-worker-runtime",
        )

    return PluginDefinitionV2(
        module_ref=AGENT_WORKER_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_WORKER_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AGENT_OPERATION_ORCHESTRATOR_SERVICE_V2",
    "AGENT_WORKER_GRAPH_RUNTIME_INJECT_V2",
    "AGENT_WORKER_ORCHESTRATION_RUNTIME_INJECT_V2",
    "AGENT_WORKER_REDIS_RUNTIME_INJECT_V2",
    "AGENT_WORKER_RUNTIME_MODULE_V2",
    "AGENT_WORKER_RUNTIME_SERVICE_V2",
    "AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2",
    "AGENT_WORKER_SUBAGENT_RUNS_INJECT_V2",
    "AgentWorkerRuntimeResolverProtocolV2",
    "AgentWorkerRuntimeResolverV2",
    "AgentWorkerRuntimeServicesV2",
    "agent_worker_graph_runtime_factory_v2",
    "agent_worker_redis_runtime_factory_v2",
    "agent_worker_runtime_definition_v2",
    "agent_worker_sandbox_runtime_factory_v2",
    "agent_worker_workspace_core_runtime_factory_v2",
    "bind_current_agent_orchestrator_v2",
    "current_agent_canvas_manager_v2",
    "current_agent_orchestrator_v2",
    "current_agent_worker_redis_client_v2",
    "current_agent_worker_runtime_services_v2",
]
