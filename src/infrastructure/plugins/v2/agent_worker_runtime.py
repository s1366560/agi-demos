"""Generation-owned runtime services consumed by Agent Worker operations."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.configuration.config import get_settings
from src.domain.ports.services.sandbox_port import SandboxConnectionError
from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter
from src.infrastructure.agent.subagent.run_registry import SubAgentRunRegistry

from .agent_orchestration_runtime import (
    AgentOrchestrationRuntimeProtocolV2,
)
from .runtime import (
    ContextV2,
    OperationContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .sandbox_runtime import SandboxRuntimeServiceV2

AGENT_WORKER_RUNTIME_MODULE_V2 = "builtin://memstack/agent/worker-runtime"
AGENT_WORKER_RUNTIME_SERVICE_V2 = "service:agent.worker-runtime"
AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2 = "sandbox_runtime"
AGENT_WORKER_SUBAGENT_RUNS_INJECT_V2 = "subagent_runs"
AGENT_WORKER_ORCHESTRATION_RUNTIME_INJECT_V2 = "orchestration_runtime"

logger = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class AgentWorkerRuntimeServicesV2:
    """Runtime capabilities resolved from one exact generation."""

    sandbox_adapter: MCPSandboxAdapter | None
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

    sandbox_runtime: SandboxRuntimeServiceV2
    subagent_run_registry: SubAgentRunRegistry
    orchestration_runtime: AgentOrchestrationRuntimeProtocolV2

    def resolve(self, operation: OperationContextV2) -> AgentWorkerRuntimeServicesV2:
        _ = operation.descriptor
        sandbox_services = self.sandbox_runtime.services
        if sandbox_services is None:
            return AgentWorkerRuntimeServicesV2(
                sandbox_adapter=None,
                subagent_run_registry=self.subagent_run_registry,
                orchestration_runtime=self.orchestration_runtime,
                unavailable_code=(
                    self.sandbox_runtime.unavailable_code or "sandbox_runtime_unavailable"
                ),
            )
        return AgentWorkerRuntimeServicesV2(
            sandbox_adapter=sandbox_services.adapter,
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


def agent_worker_runtime_definition_v2() -> PluginDefinitionV2:
    """Build the explicit Agent Worker runtime Consumer definition."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "generation-sandbox-runtime":
            raise ValueError("agent worker runtime requires strategy generation-sandbox-runtime")
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
                sandbox_runtime=sandbox_runtime,
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
    "AGENT_WORKER_ORCHESTRATION_RUNTIME_INJECT_V2",
    "AGENT_WORKER_RUNTIME_MODULE_V2",
    "AGENT_WORKER_RUNTIME_SERVICE_V2",
    "AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2",
    "AGENT_WORKER_SUBAGENT_RUNS_INJECT_V2",
    "AgentWorkerRuntimeResolverProtocolV2",
    "AgentWorkerRuntimeResolverV2",
    "AgentWorkerRuntimeServicesV2",
    "agent_worker_runtime_definition_v2",
    "agent_worker_sandbox_runtime_factory_v2",
    "current_agent_worker_runtime_services_v2",
]
