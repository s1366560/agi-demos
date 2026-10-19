"""Static feature ownership declared by builtin HTTP contributions."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, kw_only=True)
class FeatureOperationOwnerV2:
    """Ownership is declaration metadata, never inferred from request text."""

    feature_ids: tuple[str, ...]
    resources: tuple[tuple[str, str], ...] = ()
    project_aggregate: bool = False
    tenant_aggregate: Literal["support_ticket"] | None = None
    payload_field_owners: tuple[tuple[str, str, str], ...] = ()


def feature_owner_v2(
    feature_id: str,
    *resources: tuple[str, str],
    project_aggregate: bool = False,
    tenant_aggregate: Literal["support_ticket"] | None = None,
) -> FeatureOperationOwnerV2:
    return FeatureOperationOwnerV2(
        feature_ids=(feature_id,),
        resources=resources,
        project_aggregate=project_aggregate,
        tenant_aggregate=tenant_aggregate,
    )


# Exact entry and operation identifiers are part of the builtin contribution contract.
# Shared bootstrap reads and the kernel instance recovery routes are intentionally unowned.
_ENTRY_OWNERS_V2 = {
    "builtin-skills-http-routes": feature_owner_v2("tenant-skills", ("skill", "skill_id")),
    "builtin-tenant-skill-configs-http-routes": feature_owner_v2("tenant-skills"),
    "builtin-mcp-http-routes": feature_owner_v2("tenant-mcp-servers", ("mcp", "server_id")),
    "builtin-plugin-marketplace-http-routes": feature_owner_v2("tenant-plugins"),
    "builtin-tasks-http-routes": feature_owner_v2(
        "tenant-tasks", ("task", "task_id"), project_aggregate=True
    ),
    "builtin-background-tasks-http-routes": feature_owner_v2("tenant-tasks"),
    "builtin-llm-providers-http-routes": feature_owner_v2("tenant-providers"),
    "builtin-instances-http-routes": feature_owner_v2(
        "tenant-instances", ("instance", "instance_id")
    ),
    "builtin-instance-files-http-routes": feature_owner_v2(
        "tenant-instances", ("instance", "instance_id")
    ),
    "builtin-instance-channels-http-routes": feature_owner_v2(
        "tenant-instances", ("instance", "instance_id")
    ),
    "builtin-audit-http-routes": feature_owner_v2("tenant-audit-logs"),
    "builtin-billing-http-routes": feature_owner_v2("tenant-billing"),
    "builtin-clusters-http-routes": feature_owner_v2("tenant-clusters", ("cluster", "cluster_id")),
    "builtin-deploy-http-routes": feature_owner_v2(
        "tenant-deploy", ("instance", "instance_id"), ("deploy", "deploy_id")
    ),
    "builtin-events-http-routes": feature_owner_v2("tenant-events"),
    "builtin-genes-http-routes": feature_owner_v2("tenant-genes"),
    "builtin-instance-templates-http-routes": feature_owner_v2("tenant-instance-templates"),
    "builtin-memories-http-routes": feature_owner_v2(
        "project-memories", ("memory", "memory_id"), project_aggregate=True
    ),
    "builtin-enhanced-search-http-routes": feature_owner_v2(
        "project-search", project_aggregate=True
    ),
    "builtin-schema-http-routes": feature_owner_v2("project-schema"),
    "builtin-cron-http-routes": feature_owner_v2("project-cron-jobs", ("cron", "job_id")),
    "builtin-channels-http-routes": feature_owner_v2("project-channels"),
    "builtin-admin-dlq-http-routes": feature_owner_v2("tenant-dead-letter-queue"),
    "builtin-acp-http-routes": feature_owner_v2("tenant-acp"),
    "builtin-agent-pool-http-routes": feature_owner_v2("tenant-pool"),
    "builtin-graph-stores-http-routes": feature_owner_v2("tenant-backend-stores"),
    "builtin-retrieval-stores-http-routes": feature_owner_v2("tenant-backend-stores"),
    "builtin-maintenance-http-routes": feature_owner_v2(
        "project-maintenance", project_aggregate=True
    ),
    "builtin-support-http-routes": feature_owner_v2("project-support"),
    "builtin-tenant-webhooks-http-routes": feature_owner_v2("tenant-webhooks"),
    "builtin-trust-http-routes": feature_owner_v2("tenant-trust-policies"),
    "builtin-subagents-http-routes": feature_owner_v2("tenant-agents"),
}

_OPERATIONS_V2: dict[tuple[str, str], FeatureOperationOwnerV2] = {}


def _declare(entry_id: str, names: tuple[str, ...], owner: FeatureOperationOwnerV2) -> None:
    for name in names:
        _OPERATIONS_V2[(entry_id, name)] = owner


_declare(
    "builtin-support-http-routes",
    ("list_support_tickets",),
    feature_owner_v2("project-support", tenant_aggregate="support_ticket"),
)
_declare(
    "builtin-graph-http-routes",
    ("get_graph", "get_subgraph"),
    feature_owner_v2("project-graph", project_aggregate=True),
)
_declare(
    "builtin-graph-http-routes",
    ("list_entities", "get_entity_types", "get_entity", "get_entity_relationships"),
    feature_owner_v2("project-entities", ("graph_entity", "entity_id"), project_aggregate=True),
)
_declare(
    "builtin-graph-http-routes",
    ("list_communities", "get_community", "get_community_members", "rebuild_communities"),
    feature_owner_v2(
        "project-communities", ("graph_community", "community_id"), project_aggregate=True
    ),
)
_declare("builtin-projects-http-routes", ("create_project",), feature_owner_v2("tenant-projects"))
_declare(
    "builtin-trust-http-routes",
    ("list_decision_records", "get_decision_record"),
    feature_owner_v2("tenant-decision-records"),
)
_declare(
    "builtin-genes-http-routes",
    ("list_evolution_events", "create_evolution_event", "get_evolution_event"),
    feature_owner_v2("tenant-evolution"),
)
_declare(
    "builtin-reflection-http-routes",
    ("list_playbooks", "list_reflection_verdicts"),
    feature_owner_v2("project-playbooks"),
)
_declare(
    "builtin-workspace-core-http-routes",
    (
        "create_workspace",
        "update_workspace",
        "delete_workspace",
        "list_workspace_members",
        "add_workspace_member",
        "update_workspace_member",
        "remove_workspace_member",
        "list_workspace_agents",
        "bind_workspace_agent",
        "update_workspace_agent",
        "delete_workspace_agent",
        "patch_workspace_agent_policy",
    ),
    feature_owner_v2("project-workspaces"),
)
_declare(
    "builtin-workspace-core-http-routes",
    (
        "get_execution_diagnostics",
        "mutate_workspace_collaboration_surface",
        "upload_workspace_collaboration_file",
        "create_post",
        "list_posts",
        "get_post",
        "update_post",
        "delete_post",
        "list_files",
        "create_directory",
        "upload_file",
        "download_file",
        "delete_file",
        "rename_or_move_file",
        "copy_file",
        "pin_post",
        "unpin_post",
        "create_reply",
        "list_replies",
        "update_reply",
        "delete_reply",
        "create_workspace_task",
        "update_workspace_task",
        "delete_workspace_task",
        "apply_workspace_task_recovery_action",
        "assign_workspace_task_to_agent",
        "unassign_workspace_task_from_agent",
        "claim_workspace_task",
        "start_workspace_task",
        "block_workspace_task",
        "complete_workspace_task",
        "recover_workspace_plan_stale_attempts",
        "retry_workspace_plan_outbox_item",
        "pause_workspace_plan_iteration_loop",
        "resume_workspace_plan_iteration_loop",
        "trigger_workspace_plan_next_iteration",
        "request_workspace_plan_pipeline_run",
        "request_workspace_plan_delivery_contract_regeneration",
        "request_workspace_plan_node_replan",
        "reopen_blocked_workspace_plan_node",
        "accept_review_workspace_plan_node",
        "trigger_workspace_autonomy_tick",
        "retry_workspace_autonomy_attention",
        "resolve_workspace_autonomy_attention",
        "send_message",
        "create_node",
        "update_node",
        "delete_node",
        "create_edge",
        "update_edge",
        "delete_edge",
        "create_objective",
        "update_objective",
        "delete_objective",
        "project_objective_to_task",
        "create_gene",
        "update_gene",
        "delete_gene",
    ),
    feature_owner_v2("project-blackboard"),
)
_declare(
    "builtin-projects-http-routes",
    ("delete_project",),
    feature_owner_v2("project-settings"),
)
_declare(
    "builtin-projects-http-routes",
    ("update_project",),
    FeatureOperationOwnerV2(
        feature_ids=("project-settings",),
        payload_field_owners=(
            ("project_data", "memory_rules", "project-memories"),
            ("project_data", "graph_config", "project-graph"),
        ),
    ),
)
_declare(
    "builtin-projects-http-routes",
    (
        "add_project_member",
        "update_project_member",
        "remove_project_member",
        "list_project_members",
    ),
    feature_owner_v2("project-team"),
)
_declare(
    "builtin-tenants-http-routes",
    ("update_tenant", "delete_tenant"),
    feature_owner_v2("tenant-org-settings"),
)
_declare(
    "builtin-tenants-http-routes",
    (
        "add_tenant_member",
        "add_tenant_member_json",
        "update_tenant_member_role",
        "remove_tenant_member",
        "list_tenant_members",
    ),
    feature_owner_v2("tenant-users"),
)
_declare(
    "builtin-tenants-http-routes", ("get_tenant_analytics",), feature_owner_v2("tenant-analytics")
)
_declare(
    "builtin-tenants-http-routes",
    ("list_gene_policies", "upsert_gene_policy", "delete_gene_policy"),
    feature_owner_v2("tenant-genes"),
)
_declare(
    "builtin-tenants-http-routes",
    (
        "list_registries",
        "create_registry",
        "update_registry",
        "delete_registry",
        "test_registry_connection",
    ),
    feature_owner_v2("tenant-settings"),
)
_declare(
    "builtin-agent-http-routes",
    (
        "create_definition",
        "list_definitions",
        "get_definition",
        "update_definition",
        "delete_definition",
        "set_definition_enabled",
    ),
    feature_owner_v2("tenant-agent-definitions", ("definition", "definition_id")),
)
_declare(
    "builtin-agent-http-routes",
    (
        "create_binding",
        "list_bindings",
        "delete_binding",
        "set_binding_enabled",
        "list_group_bindings",
        "test_binding_match",
    ),
    feature_owner_v2("tenant-agent-bindings", ("binding", "binding_id")),
)
_declare(
    "builtin-agent-http-routes",
    ("create_template", "list_templates", "get_template", "update_template", "delete_template"),
    feature_owner_v2("tenant-templates", ("template", "template_id")),
)
_declare(
    "builtin-agent-http-routes",
    ("list_project_shared_patterns",),
    feature_owner_v2("project-agent-patterns"),
)
_declare(
    "builtin-agent-http-routes",
    ("list_patterns", "get_pattern", "delete_pattern", "reset_patterns"),
    feature_owner_v2("tenant-patterns"),
)
_declare(
    "builtin-agent-http-routes",
    ("update_tenant_agent_config", "get_hook_catalog"),
    feature_owner_v2("tenant-settings"),
)
_declare(
    "builtin-agent-http-routes",
    ("list_project_runs", "get_project_active_run_count"),
    feature_owner_v2("project-agent-logs"),
)
_declare(
    "builtin-agent-http-routes",
    ("list_tenant_runs", "get_tenant_active_run_count"),
    feature_owner_v2("tenant-agents"),
)
_declare(
    "builtin-agent-http-routes",
    (
        "list_commands",
        "create_conversation",
        "delete_conversation",
        "update_conversation_title",
        "update_conversation_config",
        "update_conversation_mode",
        "generate_conversation_title",
        "generate_summary",
        "fork_conversation",
        "edit_message",
        "request_tool_undo",
        "add_participant",
        "remove_participant",
        "set_coordinator",
        "set_focused_agent",
        "respond_to_hitl",
        "cancel_hitl_request",
        "resume_execution",
        "switch_mode",
        "approve_plan_and_start",
    ),
    feature_owner_v2("tenant-agent-workspace", ("conversation", "conversation_id")),
)


def builtin_feature_owner_v2(entry_id: str, operation_name: str) -> FeatureOperationOwnerV2 | None:
    """Read exact static declarations without interpreting paths or payload text."""
    return _OPERATIONS_V2.get((entry_id, operation_name), _ENTRY_OWNERS_V2.get(entry_id))
