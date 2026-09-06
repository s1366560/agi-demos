"""Tenant-bound builtins with leased process-owned Sandbox infrastructure."""

import inspect
from collections.abc import Mapping
from typing import Any

from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2

from .agent_worker_runtime import agent_worker_graph_runtime_factory_v2
from .boundary import GenerationHostV2
from .builtin_modules import builtin_runtime_definitions_v2
from .runtime import ContextV2, EffectResultV2, PluginDefinitionV2, RuntimeV2Error
from .sandbox_runtime import (
    SANDBOX_RUNTIME_MODULE_V2,
    SANDBOX_RUNTIME_SERVICE_V2,
    SandboxRuntimeServiceV2,
    sandbox_runtime_definition_v2,
)
from .scope import validate_scope_v2
from .workspace_core_runtime import (
    WORKSPACE_CORE_RUNTIME_MODULE_V2,
    WORKSPACE_CORE_RUNTIME_SERVICE_V2,
    WorkspaceCoreRuntimeServiceV2,
    workspace_core_runtime_definition_v2,
)


def leased_workspace_core_definition_v2(owner_host: GenerationHostV2) -> PluginDefinitionV2:
    """Borrow the owner's verified bridges without taking over their disposal."""
    contract = workspace_core_runtime_definition_v2()

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        if config.get("strategy") != "avernet-client":
            raise ValueError("Workspace Core runtime requires strategy avernet-client")
        lease = await owner_host.acquire()
        try:
            runtime = lease.generation.resolve(
                WORKSPACE_CORE_RUNTIME_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
            )
            if not isinstance(runtime, WorkspaceCoreRuntimeServiceV2):
                raise RuntimeV2Error(
                    "invalid_workspace_core_runtime_projection",
                    "owner has an invalid Workspace Core runtime",
                )
            _ = context.provide(WORKSPACE_CORE_RUNTIME_SERVICE_V2, runtime)
        except BaseException:
            await lease.release()
            raise
        return lease.release

    return PluginDefinitionV2(
        module_ref=contract.module_ref, contract_digest=contract.contract_digest, apply=apply
    )


def leased_sandbox_definition_v2(owner_host: GenerationHostV2) -> PluginDefinitionV2:
    """Retain the supplying generation until this candidate or generation disposes."""
    contract = sandbox_runtime_definition_v2()

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> EffectResultV2:
        lease = await owner_host.acquire()
        try:
            runtime = lease.generation.resolve(
                SANDBOX_RUNTIME_SERVICE_V2, ScopeV2(kind=ScopeKindV2.ROOT)
            )
            if not isinstance(runtime, SandboxRuntimeServiceV2):
                raise RuntimeV2Error(
                    "invalid_sandbox_runtime_projection", "owner has an invalid Sandbox runtime"
                )
            definition = sandbox_runtime_definition_v2(projected_runtime=runtime)
            result = definition.apply(context, config)
            if inspect.isawaitable(result):
                _ = await result
        except BaseException:
            await lease.release()
            raise
        return lease.release

    return PluginDefinitionV2(
        module_ref=contract.module_ref, contract_digest=contract.contract_digest, apply=apply
    )


def scoped_builtin_runtime_definitions_v2(
    scope: ScopeV2,
    *,
    sandbox_owner_host: GenerationHostV2,
    redis_client: object | None,
) -> tuple[PluginDefinitionV2, ...]:
    """Build definitions for one validated tenant; profile closure selects actual entries.

    Redis is borrowed from process lifetime. Shared runtimes retain an owner lease per apply.
    Graph adapters are newly allocated with the explicit tenant and own their clients.
    """
    canonical = validate_scope_v2(scope)
    if canonical.tenant_id is None:
        raise RuntimeV2Error("scope_tenant_required", "scoped builtins require a tenant")
    definitions = builtin_runtime_definitions_v2(
        graph_runtime_factory=agent_worker_graph_runtime_factory_v2(canonical.tenant_id),
        sandbox_redis_client=redis_client,
    )
    sandbox = leased_sandbox_definition_v2(sandbox_owner_host)
    workspace = leased_workspace_core_definition_v2(sandbox_owner_host)
    return tuple(
        sandbox
        if definition.module_ref == SANDBOX_RUNTIME_MODULE_V2
        else workspace
        if definition.module_ref == WORKSPACE_CORE_RUNTIME_MODULE_V2
        else definition
        for definition in definitions
    )
