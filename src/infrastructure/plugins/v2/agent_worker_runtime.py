"""Generation-owned runtime services consumed by Agent Worker operations."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.adapters.secondary.sandbox.mcp_sandbox_adapter import MCPSandboxAdapter

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


@dataclass(frozen=True, kw_only=True)
class AgentWorkerRuntimeServicesV2:
    """Runtime capabilities resolved from one exact generation."""

    sandbox_adapter: MCPSandboxAdapter | None
    unavailable_code: str | None = None


@runtime_checkable
class AgentWorkerRuntimeResolverProtocolV2(Protocol):
    """Resolve Agent Worker capabilities without exposing Provider implementations."""

    def resolve(self, operation: OperationContextV2) -> AgentWorkerRuntimeServicesV2: ...


@dataclass(frozen=True, kw_only=True)
class AgentWorkerRuntimeResolverV2:
    """Project generation-owned sandbox state into an Agent Worker operation."""

    sandbox_runtime: SandboxRuntimeServiceV2

    def resolve(self, operation: OperationContextV2) -> AgentWorkerRuntimeServicesV2:
        _ = operation.descriptor
        sandbox_services = self.sandbox_runtime.services
        if sandbox_services is None:
            return AgentWorkerRuntimeServicesV2(
                sandbox_adapter=None,
                unavailable_code=(
                    self.sandbox_runtime.unavailable_code or "sandbox_runtime_unavailable"
                ),
            )
        return AgentWorkerRuntimeServicesV2(sandbox_adapter=sandbox_services.adapter)


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
        _ = context.provide(
            AGENT_WORKER_RUNTIME_SERVICE_V2,
            AgentWorkerRuntimeResolverV2(sandbox_runtime=sandbox_runtime),
            label="agent-worker-runtime",
        )

    return PluginDefinitionV2(
        module_ref=AGENT_WORKER_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_WORKER_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AGENT_WORKER_RUNTIME_MODULE_V2",
    "AGENT_WORKER_RUNTIME_SERVICE_V2",
    "AGENT_WORKER_SANDBOX_RUNTIME_INJECT_V2",
    "AgentWorkerRuntimeResolverProtocolV2",
    "AgentWorkerRuntimeResolverV2",
    "AgentWorkerRuntimeServicesV2",
    "agent_worker_runtime_definition_v2",
]
