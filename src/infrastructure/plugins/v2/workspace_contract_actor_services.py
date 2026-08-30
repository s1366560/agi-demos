"""Generation-owned Workspace contract actor resolution seam."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from src.infrastructure.workspace_core.client import (
    WorkspaceContractActorResolveRequest,
    WorkspaceContractActorResolveResponse,
)

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)
from .workspace_core_runtime import WorkspaceCoreRuntimeServiceV2

WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2 = (
    "builtin://memstack/workspace-core/contract-actor-resolver"
)
WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2 = "service:workspace-core.contract-actor-resolver"
WORKSPACE_CONTRACT_ACTOR_RUNTIME_INJECT_V2 = "runtime"


@runtime_checkable
class WorkspaceContractActorResolverProtocolV2(Protocol):
    """Resolve the immutable actor identity for one scoped Workspace operation."""

    async def resolve(
        self,
        request: WorkspaceContractActorResolveRequest,
    ) -> WorkspaceContractActorResolveResponse: ...


@dataclass(frozen=True, kw_only=True)
class WorkspaceContractActorResolverV2:
    """Typed adapter over the generation-owned Workspace Core client."""

    runtime: WorkspaceCoreRuntimeServiceV2

    async def resolve(
        self,
        request: WorkspaceContractActorResolveRequest,
    ) -> WorkspaceContractActorResolveResponse:
        return await self.runtime.client.resolve_contract_actor(request)


def workspace_contract_actor_resolver_definition_v2() -> PluginDefinitionV2:
    """Provide fail-closed actor resolution from an explicit runtime alias."""

    def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "workspace-core-authority":
            raise ValueError(
                "Workspace contract actor resolver requires strategy workspace-core-authority"
            )
        runtime = context.require(WORKSPACE_CONTRACT_ACTOR_RUNTIME_INJECT_V2)
        if not isinstance(runtime, WorkspaceCoreRuntimeServiceV2):
            raise RuntimeV2Error(
                "invalid_workspace_core_runtime",
                "Workspace contract actor resolver received an invalid runtime Provider",
            )
        _ = context.provide(
            WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2,
            WorkspaceContractActorResolverV2(runtime=runtime),
            label="workspace-contract-actor-resolver",
        )

    return PluginDefinitionV2(
        module_ref=WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "WORKSPACE_CONTRACT_ACTOR_RESOLVER_MODULE_V2",
    "WORKSPACE_CONTRACT_ACTOR_RESOLVER_SERVICE_V2",
    "WORKSPACE_CONTRACT_ACTOR_RUNTIME_INJECT_V2",
    "WorkspaceContractActorResolverProtocolV2",
    "WorkspaceContractActorResolverV2",
    "workspace_contract_actor_resolver_definition_v2",
]
