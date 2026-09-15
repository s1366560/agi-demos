"""Exact generation admission for persisted HITL crash recovery."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from src.application.services.publication_archive_loader_v2 import load_agent_generation_archives_v2
from src.domain.model.plugins.generated_v2 import ScopeKindV2, ScopeV2
from src.infrastructure.plugins.v2.boundary import (
    OPERATION_IDENTITY_SERVICE_V2,
    OPERATION_METADATA_SERVICE_V2,
)
from src.infrastructure.plugins.v2.runtime import OperationContextV2, RuntimeV2Error

from .state_store import HITLAgentState


@asynccontextmanager
async def admit_persisted_hitl_state_v2(
    state: HITLAgentState,
    *,
    request_id: str,
) -> AsyncIterator[OperationContextV2]:
    """Admit the exact immutable generation captured when HITL paused."""
    if state.plugin_generation is None:
        raise RuntimeV2Error(
            "generation_descriptor_missing",
            "persisted HITL state does not identify the plugin generation to resume",
        )
    if state.plugin_distribution is None:
        raise RuntimeV2Error(
            "generation_distribution_missing",
            "persisted HITL state does not contain the plugin distribution to resume",
        )

    from src.infrastructure.plugins.v2.agent_worker_lifecycle_transport_v2 import (
        AgentWorkerLifecycleTransportV2,
    )
    from src.infrastructure.plugins.v2.agent_worker_runtime import (
        agent_worker_graph_runtime_factory_v2,
        agent_worker_redis_runtime_factory_v2,
        agent_worker_sandbox_runtime_factory_v2,
        agent_worker_workspace_core_runtime_factory_v2,
    )
    from src.infrastructure.plugins.v2.builtin_modules import builtin_runtime_definitions_v2
    from src.infrastructure.plugins.v2.runtime_host import DataPlaneGenerationAdmissionV2

    admission = DataPlaneGenerationAdmissionV2(
        builtin_runtime_definitions_v2(
            agent_lifecycle_connection_manager=AgentWorkerLifecycleTransportV2(),
            graph_runtime_factory=agent_worker_graph_runtime_factory_v2(state.tenant_id),
            redis_runtime_factory=agent_worker_redis_runtime_factory_v2,
            sandbox_runtime_factory=agent_worker_sandbox_runtime_factory_v2,
            workspace_core_runtime_factory=agent_worker_workspace_core_runtime_factory_v2,
        ),
        archive_loader=load_agent_generation_archives_v2,
    )
    try:
        async with admission.admit(
            descriptor_payload=state.plugin_generation,
            distribution_payload=state.plugin_distribution,
            operation_id=f"hitl-resume:{request_id}",
            scope=ScopeV2(
                kind=ScopeKindV2.SESSION,
                tenant_id=state.tenant_id,
                project_id=state.project_id,
                session_id=state.conversation_id,
            ),
            services={
                OPERATION_IDENTITY_SERVICE_V2: {
                    "tenant_id": state.tenant_id,
                    "project_id": state.project_id,
                    "user_id": state.user_id,
                },
                OPERATION_METADATA_SERVICE_V2: {
                    "kind": "hitl-resume",
                    "request_id": request_id,
                    "message_id": state.message_id,
                },
            },
        ) as operation:
            from src.application.services.wasm_operation_authority_v2 import (
                prepare_agent_wasm_tools_v2,
            )

            await prepare_agent_wasm_tools_v2(operation)
            yield operation
    finally:
        await admission.close()


__all__ = ["admit_persisted_hitl_state_v2"]
