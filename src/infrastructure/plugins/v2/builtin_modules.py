"""Trusted builtin module definitions for the first production v2 generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .agent_capabilities import (
    builtin_agent_capability_definition_v2,
    builtin_skill_contribution_v2,
    builtin_subagent_contribution_v2,
)
from .agent_definition import (
    builtin_agent_definition_contribution_v2,
    builtin_agent_definition_v2,
)
from .agent_loop import builtin_agent_loop_definition_v2
from .agent_runtime_dispatcher import (
    AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
    PinnedAgentRuntimeDispatcherV2,
)
from .agent_worker_runtime import agent_worker_runtime_definition_v2
from .backend_store_services import backend_store_service_definitions_v2
from .channel_adapters import (
    builtin_channel_adapter_catalog_definition_v2,
    builtin_feishu_channel_adapter_definition_v2,
)
from .graph_application_services import graph_application_service_definition_v2
from .graph_runtime import GraphRuntimeFactoryV2, graph_runtime_definition_v2
from .legacy_http_route_bridge import legacy_http_route_bridge_definition_v2
from .mcp_services import mcp_service_definitions_v2
from .memory_services import memory_service_definitions_v2
from .project_tenant_services import project_tenant_service_definitions_v2
from .retrieval_runtime import RetrievalRuntimeFactoryV2, retrieval_runtime_definition_v2
from .route_effects import route_table_builder_definition_v2
from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2
from .sandbox_operation_services import sandbox_operation_service_definitions_v2
from .sandbox_runtime import SandboxRuntimeFactoryV2, sandbox_service_definitions_v2
from .search_services import search_service_definition_v2
from .selection_judge import builtin_plugin_selection_judge_definition_v2
from .session_event_log import builtin_session_event_log_definition_v2
from .sisyphus_runtime import sisyphus_runtime_definitions_v2
from .system_prompt import builtin_system_prompt_definition_v2
from .telemetry_runtime import TelemetryRuntimeManagerV2, telemetry_runtime_definition_v2
from .tool_set import (
    builtin_tool_contribution_definition_v2,
    builtin_tool_set_definition_v2,
)
from .workflow_runtime import WorkflowRuntimeFactoryV2, workflow_service_definitions_v2
from .workspace_pipeline import builtin_workspace_drone_pipeline_provider_definition_v2
from .workspace_runtime import workspace_runtime_definitions_v2

RUNTIME_BOUNDARY_MODULE_V2 = "builtin://memstack/runtime/generation-boundary"
RUNTIME_BOUNDARY_SERVICE_V2 = "service:runtime-generation-boundary"


@dataclass(frozen=True, kw_only=True)
class RuntimeBoundaryServiceV2:
    """Marker resolved by data-plane boundaries from their pinned generation."""

    protocol_version: int
    owner_entry_id: str


def _apply_runtime_boundary(
    context: ContextV2,
    config: Mapping[str, Any],
) -> None:
    protocol_version = config.get("protocol_version")
    if protocol_version != 2:
        raise ValueError("runtime generation boundary requires protocol_version 2")
    _ = context.provide(
        RUNTIME_BOUNDARY_SERVICE_V2,
        RuntimeBoundaryServiceV2(
            protocol_version=protocol_version,
            owner_entry_id=context.entry_id,
        ),
        label="runtime-generation-boundary",
    )
    _ = context.provide(
        AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
        PinnedAgentRuntimeDispatcherV2(),
        label="agent-runtime-dispatcher",
    )


def builtin_runtime_definitions_v2(
    *,
    graph_runtime_factory: GraphRuntimeFactoryV2 | None = None,
    retrieval_runtime_factory: RetrievalRuntimeFactoryV2 | None = None,
    sandbox_runtime_factory: SandboxRuntimeFactoryV2 | None = None,
    sandbox_redis_client: object | None = None,
    workflow_runtime_factory: WorkflowRuntimeFactoryV2 | None = None,
    telemetry_runtime_manager: TelemetryRuntimeManagerV2 | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return deterministic, repository-owned definitions allowed in-process."""
    from .builtin_billing_http_routes import builtin_billing_http_routes_definition_v2
    from .builtin_enhanced_search_http_routes import (
        builtin_enhanced_search_http_routes_definition_v2,
    )
    from .builtin_episodes_http_routes import builtin_episodes_http_routes_definition_v2
    from .builtin_graph_http_routes import builtin_graph_http_routes_definition_v2
    from .builtin_graph_stores_http_routes import (
        builtin_graph_stores_http_routes_definition_v2,
    )
    from .builtin_invitations_http_routes import (
        builtin_invitations_http_routes_definition_v2,
    )
    from .builtin_invitations_public_http_routes import (
        builtin_invitations_public_http_routes_definition_v2,
    )
    from .builtin_memories_http_routes import builtin_memories_http_routes_definition_v2
    from .builtin_project_my_work_http_routes import (
        builtin_project_my_work_http_routes_definition_v2,
    )
    from .builtin_projects_http_routes import builtin_projects_http_routes_definition_v2
    from .builtin_recall_http_routes import builtin_recall_http_routes_definition_v2
    from .builtin_retrieval_stores_http_routes import (
        builtin_retrieval_stores_http_routes_definition_v2,
    )
    from .builtin_smtp_config_http_routes import (
        builtin_smtp_config_http_routes_definition_v2,
    )
    from .builtin_system_http_routes import builtin_system_http_routes_definition_v2
    from .builtin_tenant_webhooks_http_routes import (
        builtin_tenant_webhooks_http_routes_definition_v2,
    )
    from .builtin_tenants_http_routes import builtin_tenants_http_routes_definition_v2
    from .builtin_trust_workspace_http_routes import (
        builtin_trust_workspace_http_routes_definition_v2,
    )

    return (
        PluginDefinitionV2(
            module_ref=RUNTIME_BOUNDARY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(RUNTIME_BOUNDARY_MODULE_V2),
            apply=_apply_runtime_boundary,
        ),
        telemetry_runtime_definition_v2(telemetry_runtime_manager),
        graph_runtime_definition_v2(graph_runtime_factory),
        graph_application_service_definition_v2(),
        *sandbox_service_definitions_v2(
            sandbox_runtime_factory,
            redis_client=sandbox_redis_client,
        ),
        agent_worker_runtime_definition_v2(),
        *sandbox_operation_service_definitions_v2(
            redis_client=sandbox_redis_client,
        ),
        *mcp_service_definitions_v2(redis_client=sandbox_redis_client),
        *workflow_service_definitions_v2(workflow_runtime_factory),
        retrieval_runtime_definition_v2(retrieval_runtime_factory),
        search_service_definition_v2(),
        *memory_service_definitions_v2(),
        builtin_channel_adapter_catalog_definition_v2(),
        builtin_feishu_channel_adapter_definition_v2(),
        route_table_builder_definition_v2(),
        builtin_tenants_http_routes_definition_v2(),
        builtin_project_my_work_http_routes_definition_v2(),
        builtin_projects_http_routes_definition_v2(),
        builtin_memories_http_routes_definition_v2(),
        builtin_graph_http_routes_definition_v2(),
        builtin_graph_stores_http_routes_definition_v2(),
        builtin_episodes_http_routes_definition_v2(),
        builtin_recall_http_routes_definition_v2(),
        builtin_retrieval_stores_http_routes_definition_v2(),
        builtin_enhanced_search_http_routes_definition_v2(),
        builtin_billing_http_routes_definition_v2(),
        builtin_trust_workspace_http_routes_definition_v2(),
        builtin_smtp_config_http_routes_definition_v2(),
        builtin_tenant_webhooks_http_routes_definition_v2(),
        builtin_system_http_routes_definition_v2(),
        builtin_invitations_http_routes_definition_v2(),
        builtin_invitations_public_http_routes_definition_v2(),
        legacy_http_route_bridge_definition_v2(),
        *project_tenant_service_definitions_v2(),
        *backend_store_service_definitions_v2(),
        builtin_agent_loop_definition_v2(),
        builtin_system_prompt_definition_v2(),
        builtin_tool_set_definition_v2(),
        builtin_tool_contribution_definition_v2(),
        builtin_agent_definition_v2(),
        builtin_agent_definition_contribution_v2(),
        builtin_agent_capability_definition_v2(),
        builtin_skill_contribution_v2(),
        builtin_subagent_contribution_v2(),
        builtin_session_event_log_definition_v2(),
        builtin_plugin_selection_judge_definition_v2(),
        builtin_workspace_drone_pipeline_provider_definition_v2(),
        *sisyphus_runtime_definitions_v2(),
        *workspace_runtime_definitions_v2(),
    )
