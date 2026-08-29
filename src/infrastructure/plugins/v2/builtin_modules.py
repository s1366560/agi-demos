"""Trusted builtin module definitions for the first production v2 generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .admin_dlq_services import admin_dlq_service_definitions_v2
from .agent_binding_services import agent_binding_definition_v2
from .agent_canvas_tools import builtin_agent_canvas_tool_contribution_definition_v2
from .agent_capabilities import (
    builtin_agent_capability_definition_v2,
    builtin_skill_contribution_v2,
    builtin_subagent_contribution_v2,
)
from .agent_commands import (
    builtin_agent_command_catalog_definition_v2,
    builtin_agent_command_contribution_definition_v2,
)
from .agent_custom_tools import builtin_agent_custom_tool_contribution_definition_v2
from .agent_default_selection import builtin_agent_default_selection_definition_v2
from .agent_definition import (
    builtin_agent_definition_contribution_v2,
    builtin_agent_definition_v2,
)
from .agent_event_query_services import agent_event_query_service_definitions_v2
from .agent_execution_query_services import agent_execution_query_service_definitions_v2
from .agent_execution_resume_services import agent_execution_resume_definition_v2
from .agent_hitl_tools import builtin_agent_hitl_tool_contribution_definition_v2
from .agent_lifecycle_notifier import (
    AgentLifecycleConnectionManagerV2,
    agent_lifecycle_notifier_definition_v2,
)
from .agent_lifecycle_runtime import agent_lifecycle_definitions_v2
from .agent_loop import builtin_agent_loop_definition_v2
from .agent_memory_tools import builtin_agent_memory_tool_contribution_definition_v2
from .agent_model_awareness_tools import (
    builtin_agent_model_awareness_tool_contribution_definition_v2,
)
from .agent_orchestration_runtime import (
    AgentOrchestratorFactoryV2,
    agent_orchestration_runtime_definition_v2,
)
from .agent_orchestration_tools import (
    builtin_agent_orchestration_tool_contribution_definition_v2,
)
from .agent_persisted_definition import builtin_agent_persisted_definition_contribution_v2
from .agent_recovery_stream_services import agent_recovery_stream_service_definitions_v2
from .agent_routing import builtin_agent_routing_definition_v2
from .agent_runtime_dispatcher import (
    AGENT_RUNTIME_DISPATCHER_SERVICE_V2,
    PinnedAgentRuntimeDispatcherV2,
)
from .agent_runtime_utility_tools import (
    builtin_agent_runtime_utility_tool_contribution_definitions_v2,
)
from .agent_sandbox_mcp_tools import (
    builtin_agent_sandbox_mcp_tool_contribution_definition_v2,
)
from .agent_skill_mcp_service import builtin_skill_mcp_manager_definition_v2
from .agent_system_api_tool import builtin_agent_system_api_tool_contribution_definition_v2
from .agent_task_session_tools import (
    builtin_agent_task_session_tool_contribution_definitions_v2,
)
from .agent_turn_services import agent_turn_service_definitions_v2
from .agent_worker_runtime import agent_worker_runtime_definition_v2
from .agent_workflow_status_services import agent_workflow_status_definition_v2
from .ai_tool_services import ai_tool_service_definitions_v2
from .artifact_content_gc_runtime import artifact_content_gc_definitions_v2
from .artifact_content_services import artifact_content_service_definitions_v2
from .artifact_http_services import artifact_http_service_definitions_v2
from .artifact_lifecycle_services import artifact_lifecycle_service_definitions_v2
from .attachment_services import attachment_service_definitions_v2
from .audit_services import audit_service_definitions_v2
from .backend_store_services import backend_store_service_definitions_v2
from .background_task_services import background_task_service_definitions_v2
from .billing_services import billing_service_definitions_v2
from .channel_adapters import (
    builtin_channel_adapter_catalog_definition_v2,
    builtin_feishu_channel_adapter_definition_v2,
)
from .channel_runtime import ChannelRuntimeManagerV2, channel_runtime_definition_v2
from .cluster_services import cluster_service_definitions_v2
from .conversation_access_services import conversation_access_service_definitions_v2
from .conversation_collection_repository import conversation_collection_repository_definition_v2
from .conversation_collection_services import conversation_collection_service_definitions_v2
from .conversation_config_services import conversation_config_definition_v2
from .conversation_context_status_services import conversation_context_status_definitions_v2
from .conversation_enrichment_judge import conversation_enrichment_judge_definition_v2
from .conversation_generation_services import conversation_generation_definition_v2
from .conversation_participant_services import conversation_participant_definition_v2
from .conversation_revision_services import conversation_revision_definitions_v2
from .cron_services import cron_service_definitions_v2
from .docker_monitor_runtime import docker_event_monitor_definition_v2
from .engine_services import engine_catalog_definition_v2
from .event_log_services import event_log_service_definitions_v2
from .gene_services import gene_service_definitions_v2
from .graph_application_services import graph_application_service_definition_v2
from .graph_runtime import GraphRuntimeFactoryV2, graph_runtime_definition_v2
from .instance_channel_services import instance_channel_service_definitions_v2
from .instance_deploy_services import instance_deploy_service_definitions_v2
from .instance_file_services import instance_file_service_definitions_v2
from .instance_template_services import instance_template_service_definitions_v2
from .invitation_services import invitation_service_definitions_v2
from .llm_client_service import builtin_tenant_llm_client_factory_definition_v2
from .llm_health_runtime import llm_health_runtime_definition_v2
from .mcp_services import mcp_service_definitions_v2
from .memory_services import memory_service_definitions_v2
from .notification_services import notification_service_definitions_v2
from .project_access_services import project_access_definitions_v2
from .project_tenant_services import project_tenant_service_definitions_v2
from .redis_runtime import RedisRuntimeFactoryV2, redis_runtime_definition_v2
from .reflection_runtime import ReflectionRuntimeManagerV2, reflection_runtime_definition_v2
from .reflection_services import reflection_service_definitions_v2
from .retrieval_runtime import RetrievalRuntimeFactoryV2, retrieval_runtime_definition_v2
from .route_effects import route_table_builder_definition_v2
from .runtime import ContextV2, PluginDefinitionV2, generated_contract_digest_v2
from .sandbox_http_service_registry import sandbox_http_service_registry_definition_v2
from .sandbox_operation_services import sandbox_operation_service_definitions_v2
from .sandbox_runtime import SandboxRuntimeFactoryV2, sandbox_service_definitions_v2
from .schema_services import schema_service_definitions_v2
from .search_services import search_service_definition_v2
from .selection_judge import builtin_plugin_selection_judge_definition_v2
from .session_event_log import builtin_session_event_log_definition_v2
from .shares_services import shares_service_definitions_v2
from .sisyphus_runtime import sisyphus_runtime_definitions_v2
from .skill_evolution_runtime import skill_evolution_scheduler_definition_v2
from .smtp_config_services import smtp_config_service_definitions_v2
from .subagent_run_registry_service import (
    SubAgentRunRegistryFactoryV2,
    subagent_run_registry_definition_v2,
)
from .support_ticket_services import support_ticket_service_definitions_v2
from .system_prompt import builtin_system_prompt_definition_v2
from .task_log_services import task_log_service_definitions_v2
from .telemetry_runtime import TelemetryRuntimeManagerV2, telemetry_runtime_definition_v2
from .tenant_agent_config_services import tenant_agent_config_service_definitions_v2
from .tenant_skill_config_services import tenant_skill_config_service_definitions_v2
from .tenant_webhook_services import tenant_webhook_service_definitions_v2
from .tool_set import builtin_tool_set_definition_v2
from .tunnel_services import tunnel_service_definitions_v2
from .workflow_pattern_services import workflow_pattern_service_definitions_v2
from .workflow_runtime import WorkflowRuntimeFactoryV2, workflow_service_definitions_v2
from .workspace_context_services import workspace_context_service_definitions_v2
from .workspace_core_runtime import (
    WorkspaceCoreRuntimeFactoryV2,
    workspace_core_runtime_definition_v2,
)
from .workspace_pipeline import builtin_workspace_drone_pipeline_provider_definition_v2
from .workspace_runtime import workspace_runtime_definitions_v2
from .workspace_wtp_publisher import workspace_wtp_publisher_definition_v2

if TYPE_CHECKING:
    from .agent_pool_runtime import AgentPoolRuntimeFactoryV2

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


def builtin_runtime_definitions_v2(  # noqa: PLR0913
    *,
    agent_lifecycle_connection_manager: AgentLifecycleConnectionManagerV2 | None = None,
    agent_pool_runtime_factory: AgentPoolRuntimeFactoryV2 | None = None,
    graph_runtime_factory: GraphRuntimeFactoryV2 | None = None,
    retrieval_runtime_factory: RetrievalRuntimeFactoryV2 | None = None,
    redis_runtime_factory: RedisRuntimeFactoryV2 | None = None,
    sandbox_runtime_factory: SandboxRuntimeFactoryV2 | None = None,
    sandbox_redis_client: object | None = None,
    workflow_runtime_factory: WorkflowRuntimeFactoryV2 | None = None,
    telemetry_runtime_manager: TelemetryRuntimeManagerV2 | None = None,
    channel_runtime_manager: ChannelRuntimeManagerV2 | None = None,
    reflection_runtime_manager: ReflectionRuntimeManagerV2 | None = None,
    workspace_core_runtime_factory: WorkspaceCoreRuntimeFactoryV2 | None = None,
    subagent_run_registry_factory: SubAgentRunRegistryFactoryV2 | None = None,
    agent_orchestrator_factory: AgentOrchestratorFactoryV2 | None = None,
) -> tuple[PluginDefinitionV2, ...]:
    """Return deterministic, repository-owned definitions allowed in-process."""
    from . import (
        agent_pool_runtime,
        builtin_acp_http_routes,
        builtin_agent_http_routes,
        builtin_agent_pool_http_routes,
        builtin_auth_http_routes,
        builtin_channels_http_routes,
        builtin_genes_http_routes,
        builtin_llm_providers_http_routes,
        builtin_maintenance_http_routes,
        builtin_observability_http_routes,
        builtin_platform_plugins_http_routes,
        builtin_plugin_marketplace_http_routes,
        builtin_skills_http_routes,
        builtin_subagents_http_routes,
        builtin_task_session_http_routes,
        builtin_tasks_http_routes,
        builtin_websocket_http_routes,
        builtin_workspace_core_http_routes,
        builtin_workspace_core_provider_http_routes,
        builtin_workspace_core_static_http_routes,
    )
    from .builtin_admin_dlq_http_routes import builtin_admin_dlq_http_routes_definition_v2
    from .builtin_ai_tools_http_routes import builtin_ai_tools_http_routes_definition_v2
    from .builtin_artifacts_http_routes import builtin_artifacts_http_routes_definition_v2
    from .builtin_attachments_upload_http_routes import (
        builtin_attachments_upload_http_routes_definition_v2,
    )
    from .builtin_audit_http_routes import builtin_audit_http_routes_definition_v2
    from .builtin_background_tasks_http_routes import (
        builtin_background_tasks_http_routes_definition_v2,
    )
    from .builtin_billing_http_routes import builtin_billing_http_routes_definition_v2
    from .builtin_clusters_http_routes import builtin_clusters_http_routes_definition_v2
    from .builtin_cron_http_routes import builtin_cron_http_routes_definition_v2
    from .builtin_data_export_http_routes import builtin_data_export_http_routes_definition_v2
    from .builtin_deploy_http_routes import builtin_deploy_http_routes_definition_v2
    from .builtin_engines_http_routes import builtin_engines_http_routes_definition_v2
    from .builtin_enhanced_search_http_routes import (
        builtin_enhanced_search_http_routes_definition_v2,
    )
    from .builtin_episodes_http_routes import builtin_episodes_http_routes_definition_v2
    from .builtin_events_http_routes import builtin_events_http_routes_definition_v2
    from .builtin_graph_http_routes import builtin_graph_http_routes_definition_v2
    from .builtin_graph_stores_http_routes import (
        builtin_graph_stores_http_routes_definition_v2,
    )
    from .builtin_instance_channels_http_routes import (
        builtin_instance_channels_http_routes_definition_v2,
    )
    from .builtin_instance_files_http_routes import (
        builtin_instance_files_http_routes_definition_v2,
    )
    from .builtin_instance_templates_http_routes import (
        builtin_instance_templates_http_routes_definition_v2,
    )
    from .builtin_instances_http_routes import builtin_instances_http_routes_definition_v2
    from .builtin_invitations_http_routes import (
        builtin_invitations_http_routes_definition_v2,
    )
    from .builtin_invitations_public_http_routes import (
        builtin_invitations_public_http_routes_definition_v2,
    )
    from .builtin_mcp_http_routes import builtin_mcp_http_routes_definition_v2
    from .builtin_memories_http_routes import builtin_memories_http_routes_definition_v2
    from .builtin_notifications_http_routes import (
        builtin_notifications_http_routes_definition_v2,
    )
    from .builtin_project_my_work_http_routes import (
        builtin_project_my_work_http_routes_definition_v2,
    )
    from .builtin_project_sandbox_http_routes import (
        builtin_project_sandbox_http_routes_definition_v2,
    )
    from .builtin_projects_http_routes import builtin_projects_http_routes_definition_v2
    from .builtin_recall_http_routes import builtin_recall_http_routes_definition_v2
    from .builtin_reflection_http_routes import (
        builtin_reflection_http_routes_definition_v2,
    )
    from .builtin_retrieval_stores_http_routes import (
        builtin_retrieval_stores_http_routes_definition_v2,
    )
    from .builtin_sandbox_http_routes import builtin_sandbox_http_routes_definition_v2
    from .builtin_schema_http_routes import builtin_schema_http_routes_definition_v2
    from .builtin_security_ws_http_routes import builtin_security_ws_http_routes_definition_v2
    from .builtin_shares_http_routes import builtin_shares_http_routes_definition_v2
    from .builtin_smtp_config_http_routes import (
        builtin_smtp_config_http_routes_definition_v2,
    )
    from .builtin_support_http_routes import builtin_support_http_routes_definition_v2
    from .builtin_system_http_routes import builtin_system_http_routes_definition_v2
    from .builtin_tenant_skill_configs_http_routes import (
        builtin_tenant_skill_configs_http_routes_definition_v2,
    )
    from .builtin_tenant_webhooks_http_routes import (
        builtin_tenant_webhooks_http_routes_definition_v2,
    )
    from .builtin_tenants_http_routes import builtin_tenants_http_routes_definition_v2
    from .builtin_terminal_http_routes import builtin_terminal_http_routes_definition_v2
    from .builtin_trust_http_routes import builtin_trust_http_routes_definition_v2
    from .builtin_trust_workspace_http_routes import (
        builtin_trust_workspace_http_routes_definition_v2,
    )
    from .builtin_tunnel_http_routes import builtin_tunnel_http_routes_definition_v2
    from .builtin_voice_websocket_http_routes import (
        builtin_voice_websocket_http_routes_definition_v2,
    )
    from .builtin_webhooks_http_routes import builtin_webhooks_http_routes_definition_v2

    return (
        PluginDefinitionV2(
            module_ref=RUNTIME_BOUNDARY_MODULE_V2,
            contract_digest=generated_contract_digest_v2(RUNTIME_BOUNDARY_MODULE_V2),
            apply=_apply_runtime_boundary,
        ),
        redis_runtime_definition_v2(
            sandbox_redis_client,
            factory=redis_runtime_factory,
        ),
        workspace_wtp_publisher_definition_v2(),
        telemetry_runtime_definition_v2(telemetry_runtime_manager),
        workspace_core_runtime_definition_v2(workspace_core_runtime_factory),
        graph_runtime_definition_v2(graph_runtime_factory),
        graph_application_service_definition_v2(),
        *sandbox_service_definitions_v2(
            sandbox_runtime_factory,
            redis_client=sandbox_redis_client,
        ),
        sandbox_http_service_registry_definition_v2(
            redis_client=sandbox_redis_client,
        ),
        subagent_run_registry_definition_v2(subagent_run_registry_factory),
        agent_orchestration_runtime_definition_v2(agent_orchestrator_factory),
        agent_worker_runtime_definition_v2(),
        agent_pool_runtime.agent_pool_runtime_definition_v2(agent_pool_runtime_factory),
        *sandbox_operation_service_definitions_v2(
            redis_client=sandbox_redis_client,
        ),
        *mcp_service_definitions_v2(redis_client=sandbox_redis_client),
        *artifact_content_gc_definitions_v2(),
        *artifact_content_service_definitions_v2(),
        *artifact_lifecycle_service_definitions_v2(),
        *artifact_http_service_definitions_v2(),
        *attachment_service_definitions_v2(),
        *cluster_service_definitions_v2(),
        *gene_service_definitions_v2(),
        *tenant_skill_config_service_definitions_v2(),
        *tenant_agent_config_service_definitions_v2(),
        *admin_dlq_service_definitions_v2(),
        *tunnel_service_definitions_v2(),
        *audit_service_definitions_v2(),
        *billing_service_definitions_v2(),
        *workspace_context_service_definitions_v2(),
        *shares_service_definitions_v2(),
        *invitation_service_definitions_v2(),
        *smtp_config_service_definitions_v2(),
        *tenant_webhook_service_definitions_v2(),
        *instance_deploy_service_definitions_v2(redis_client=sandbox_redis_client),
        *instance_file_service_definitions_v2(),
        *instance_channel_service_definitions_v2(),
        *instance_template_service_definitions_v2(),
        docker_event_monitor_definition_v2(),
        llm_health_runtime_definition_v2(),
        skill_evolution_scheduler_definition_v2(),
        *background_task_service_definitions_v2(),
        *conversation_access_service_definitions_v2(),
        agent_binding_definition_v2(),
        *conversation_context_status_definitions_v2(),
        *conversation_revision_definitions_v2(),
        conversation_collection_repository_definition_v2(),
        conversation_config_definition_v2(),
        conversation_participant_definition_v2(),
        conversation_enrichment_judge_definition_v2(),
        conversation_generation_definition_v2(),
        *conversation_collection_service_definitions_v2(),
        *agent_event_query_service_definitions_v2(),
        agent_execution_resume_definition_v2(),
        agent_workflow_status_definition_v2(),
        *agent_execution_query_service_definitions_v2(),
        *agent_recovery_stream_service_definitions_v2(),
        *agent_turn_service_definitions_v2(),
        *task_log_service_definitions_v2(),
        *workflow_service_definitions_v2(workflow_runtime_factory),
        retrieval_runtime_definition_v2(retrieval_runtime_factory),
        search_service_definition_v2(),
        *memory_service_definitions_v2(),
        builtin_channel_adapter_catalog_definition_v2(),
        builtin_feishu_channel_adapter_definition_v2(),
        channel_runtime_definition_v2(channel_runtime_manager),
        engine_catalog_definition_v2(),
        route_table_builder_definition_v2(),
        builtin_auth_http_routes.builtin_auth_http_routes_definition_v2(),
        builtin_workspace_core_static_http_routes.builtin_workspace_core_static_http_routes_definition_v2(),
        builtin_tenants_http_routes_definition_v2(),
        builtin_project_my_work_http_routes_definition_v2(),
        builtin_projects_http_routes_definition_v2(),
        builtin_agent_http_routes.builtin_agent_http_routes_definition_v2(),
        builtin_shares_http_routes_definition_v2(),
        builtin_memories_http_routes_definition_v2(),
        builtin_project_sandbox_http_routes_definition_v2(),
        builtin_skills_http_routes.builtin_skills_http_routes_definition_v2(),
        builtin_tenant_skill_configs_http_routes_definition_v2(),
        builtin_subagents_http_routes.builtin_subagents_http_routes_definition_v2(),
        builtin_mcp_http_routes_definition_v2(),
        builtin_sandbox_http_routes_definition_v2(),
        builtin_terminal_http_routes_definition_v2(),
        builtin_artifacts_http_routes_definition_v2(),
        builtin_attachments_upload_http_routes_definition_v2(),
        builtin_channels_http_routes.builtin_channels_http_routes_definition_v2(),
        builtin_instances_http_routes_definition_v2(),
        builtin_instance_files_http_routes_definition_v2(),
        builtin_instance_channels_http_routes_definition_v2(),
        builtin_deploy_http_routes_definition_v2(),
        builtin_clusters_http_routes_definition_v2(),
        builtin_genes_http_routes.builtin_genes_http_routes_definition_v2(),
        builtin_instance_templates_http_routes_definition_v2(),
        builtin_audit_http_routes_definition_v2(),
        builtin_trust_http_routes_definition_v2(),
        builtin_engines_http_routes_definition_v2(),
        builtin_security_ws_http_routes_definition_v2(),
        builtin_websocket_http_routes.builtin_websocket_http_routes_definition_v2(),
        builtin_acp_http_routes.builtin_acp_http_routes_definition_v2(),
        builtin_observability_http_routes.builtin_observability_http_routes_definition_v2(),
        builtin_voice_websocket_http_routes_definition_v2(),
        builtin_notifications_http_routes_definition_v2(),
        builtin_events_http_routes_definition_v2(),
        builtin_tunnel_http_routes_definition_v2(),
        builtin_support_http_routes_definition_v2(),
        builtin_graph_http_routes_definition_v2(),
        builtin_graph_stores_http_routes_definition_v2(),
        builtin_episodes_http_routes_definition_v2(),
        builtin_recall_http_routes_definition_v2(),
        builtin_reflection_http_routes_definition_v2(),
        builtin_schema_http_routes_definition_v2(),
        builtin_llm_providers_http_routes.builtin_llm_providers_http_routes_definition_v2(),
        builtin_retrieval_stores_http_routes_definition_v2(),
        builtin_enhanced_search_http_routes_definition_v2(),
        builtin_data_export_http_routes_definition_v2(),
        builtin_maintenance_http_routes.builtin_maintenance_http_routes_definition_v2(),
        builtin_tasks_http_routes.builtin_tasks_http_routes_definition_v2(),
        builtin_workspace_core_http_routes.builtin_workspace_core_http_routes_definition_v2(),
        builtin_workspace_core_provider_http_routes.builtin_workspace_core_provider_http_routes_definition_v2(),
        builtin_task_session_http_routes.builtin_task_session_http_routes_definition_v2(),
        builtin_cron_http_routes_definition_v2(),
        builtin_ai_tools_http_routes_definition_v2(),
        builtin_background_tasks_http_routes_definition_v2(),
        builtin_billing_http_routes_definition_v2(),
        builtin_trust_workspace_http_routes_definition_v2(),
        builtin_smtp_config_http_routes_definition_v2(),
        builtin_webhooks_http_routes_definition_v2(),
        builtin_tenant_webhooks_http_routes_definition_v2(),
        builtin_system_http_routes_definition_v2(),
        builtin_plugin_marketplace_http_routes.builtin_plugin_marketplace_http_routes_definition_v2(),
        builtin_platform_plugins_http_routes.builtin_platform_plugins_http_routes_definition_v2(),
        builtin_admin_dlq_http_routes_definition_v2(),
        builtin_invitations_http_routes_definition_v2(),
        builtin_invitations_public_http_routes_definition_v2(),
        builtin_agent_pool_http_routes.builtin_agent_pool_http_routes_definition_v2(),
        *project_access_definitions_v2(),
        *project_tenant_service_definitions_v2(),
        *cron_service_definitions_v2(),
        *reflection_service_definitions_v2(),
        *schema_service_definitions_v2(),
        *notification_service_definitions_v2(),
        *event_log_service_definitions_v2(),
        *workflow_pattern_service_definitions_v2(),
        *support_ticket_service_definitions_v2(),
        *ai_tool_service_definitions_v2(),
        *backend_store_service_definitions_v2(),
        builtin_tenant_llm_client_factory_definition_v2(),
        reflection_runtime_definition_v2(reflection_runtime_manager),
        agent_lifecycle_notifier_definition_v2(agent_lifecycle_connection_manager),
        builtin_agent_loop_definition_v2(),
        builtin_system_prompt_definition_v2(),
        builtin_tool_set_definition_v2(),
        builtin_agent_command_catalog_definition_v2(),
        builtin_agent_command_contribution_definition_v2(),
        builtin_skill_mcp_manager_definition_v2(),
        builtin_agent_hitl_tool_contribution_definition_v2(),
        builtin_agent_memory_tool_contribution_definition_v2(),
        builtin_agent_model_awareness_tool_contribution_definition_v2(),
        builtin_agent_system_api_tool_contribution_definition_v2(),
        builtin_agent_canvas_tool_contribution_definition_v2(),
        builtin_agent_custom_tool_contribution_definition_v2(),
        builtin_agent_sandbox_mcp_tool_contribution_definition_v2(),
        *builtin_agent_task_session_tool_contribution_definitions_v2(),
        *builtin_agent_runtime_utility_tool_contribution_definitions_v2(),
        builtin_agent_orchestration_tool_contribution_definition_v2(),
        builtin_agent_definition_v2(),
        builtin_agent_default_selection_definition_v2(),
        builtin_agent_routing_definition_v2(),
        builtin_agent_persisted_definition_contribution_v2(),
        builtin_agent_definition_contribution_v2(),
        builtin_agent_capability_definition_v2(),
        builtin_skill_contribution_v2(),
        builtin_subagent_contribution_v2(),
        builtin_session_event_log_definition_v2(),
        builtin_plugin_selection_judge_definition_v2(),
        builtin_workspace_drone_pipeline_provider_definition_v2(),
        *agent_lifecycle_definitions_v2(),
        *sisyphus_runtime_definitions_v2(),
        *workspace_runtime_definitions_v2(),
    )
