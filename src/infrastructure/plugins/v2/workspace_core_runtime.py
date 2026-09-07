"""Generation-owned Workspace Core runtime Provider primitive."""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from src.configuration.workspace_core import WorkspaceCoreSettings
from src.domain.ports.services.workspace_access_verifier_port import WorkspaceAccessVerifier
from src.domain.ports.services.workspace_authority_port import WorkspaceAuthorityPort
from src.infrastructure.workspace_core.autonomy_judge import WorkspaceAutonomyJudgePort
from src.infrastructure.workspace_core.client import WorkspaceCoreClient
from src.infrastructure.workspace_core.context_judge import WorkspaceContextJudgePort
from src.infrastructure.workspace_core.plan_judge import WorkspacePlanJudgePort
from src.infrastructure.workspace_core.provider import (
    AvernetProviderAdapter,
    ProviderEventSink,
    ProviderRuntimePort,
)

from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

WORKSPACE_CORE_RUNTIME_MODULE_V2 = "builtin://memstack/workspace-core/runtime"
WORKSPACE_CORE_RUNTIME_SERVICE_V2 = "service:workspace-core.runtime"


@dataclass(frozen=True, kw_only=True)
class WorkspaceCoreRuntimeServiceV2:
    """Complete shadow-ready Workspace Core resources owned by one generation."""

    settings: WorkspaceCoreSettings
    client: WorkspaceCoreClient
    authority: WorkspaceAuthorityPort
    context_judge: WorkspaceContextJudgePort
    plan_judge: WorkspacePlanJudgePort
    autonomy_judge: WorkspaceAutonomyJudgePort
    access_verifier: WorkspaceAccessVerifier
    event_sink: ProviderEventSink
    agent_runtime_provider: ProviderRuntimePort
    provider_adapter: AvernetProviderAdapter

    async def dispose(self) -> None:
        """Drain generation-owned Provider bridges before releasing the service."""
        await self.provider_adapter.wait_until_idle()


type WorkspaceCoreRuntimeFactoryV2 = Callable[
    [],
    WorkspaceCoreRuntimeServiceV2 | Awaitable[WorkspaceCoreRuntimeServiceV2],
]


def workspace_core_runtime_definition_v2(
    workspace_core_runtime_factory: WorkspaceCoreRuntimeFactoryV2 | None = None,
) -> PluginDefinitionV2:
    """Build a fail-closed Workspace Core Provider definition."""

    async def apply(context: ContextV2, config: Mapping[str, Any]) -> None:
        if config.get("strategy") != "avernet-client":
            raise ValueError("Workspace Core runtime requires strategy avernet-client")
        if workspace_core_runtime_factory is None:
            raise RuntimeV2Error(
                "workspace_core_runtime_factory_unavailable",
                "enabled Workspace Core runtime has no data-plane factory",
            )

        runtime: WorkspaceCoreRuntimeServiceV2 | None = None

        async def acquire() -> Callable[[], Awaitable[None]]:
            nonlocal runtime
            candidate = workspace_core_runtime_factory()
            if inspect.isawaitable(candidate):
                candidate = await candidate
            if not isinstance(candidate, WorkspaceCoreRuntimeServiceV2):
                raise RuntimeV2Error(
                    "invalid_workspace_core_runtime_factory_result",
                    "Workspace Core runtime factory returned an invalid service",
                )
            runtime = candidate
            return candidate.dispose

        await context.effect(acquire, label="workspace-core-runtime")
        if runtime is None:
            raise RuntimeV2Error(
                "workspace_core_runtime_acquisition_failed",
                "Workspace Core runtime acquisition completed without a service",
            )
        _ = context.provide(
            WORKSPACE_CORE_RUNTIME_SERVICE_V2,
            runtime,
            label="workspace-core-runtime-provider",
        )

    return PluginDefinitionV2(
        module_ref=WORKSPACE_CORE_RUNTIME_MODULE_V2,
        contract_digest=generated_contract_digest_v2(WORKSPACE_CORE_RUNTIME_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "WORKSPACE_CORE_RUNTIME_MODULE_V2",
    "WORKSPACE_CORE_RUNTIME_SERVICE_V2",
    "WorkspaceCoreRuntimeFactoryV2",
    "WorkspaceCoreRuntimeServiceV2",
    "workspace_core_runtime_definition_v2",
]
