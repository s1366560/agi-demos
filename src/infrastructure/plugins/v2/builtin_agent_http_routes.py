"""V2-owned production contributions for the builtin agent HTTP row."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from src.application.schemas import (
    agent_run_authority as run_schemas,
    conversation_session_projection as session_schemas,
)
from src.infrastructure.adapters.primary.web.routers.agent import (
    agent_graph_router as graph,
    binding_router as binding,
    commands,
    config,
    conversations,
    definitions_router as definitions,
    events,
    hitl,
    messages,
    participants,
    patterns,
    plans,
    run_input_authority as run_input,
    run_review_authority as run_review,
    schemas,
    session_projection as session,
    subagent_router as subagent,
    templates,
    tools,
    trace_router as trace,
)

from .http_routes import RouteDefinitionV2, RouteTableBuilderV2
from .route_effects import ROUTE_TABLE_BUILDER_INJECT_V2
from .runtime import (
    ContextV2,
    PluginDefinitionV2,
    RuntimeV2Error,
    generated_contract_digest_v2,
)

AGENT_HTTP_ROUTES_ENTRY_V2 = "builtin-agent-http-routes"
AGENT_HTTP_ROUTES_MODULE_V2 = "builtin://memstack/http/agent-routes"
AGENT_HTTP_ROUTES_ROW_V2 = "agent"
_AGENT_PREFIX_V2 = "/api/v1/agent"

type AgentRouteSpecV2 = tuple[Callable[..., Any], object | None, str, str]

_AGENT_ROUTE_SPECS_V2: tuple[AgentRouteSpecV2, ...] = (
    (commands.list_commands, schemas.CommandsListResponse, "GET", "/commands"),
    (conversations.create_conversation, schemas.ConversationResponse, "POST", "/conversations"),
    (
        conversations.list_conversations,
        schemas.PaginatedConversationsResponse,
        "GET",
        "/conversations",
    ),
    (
        conversations.get_conversation,
        schemas.ConversationResponse,
        "GET",
        "/conversations/{conversation_id}",
    ),
    (
        conversations.get_context_status,
        dict[str, Any],
        "GET",
        "/conversations/{conversation_id}/context-status",
    ),
    (conversations.delete_conversation, None, "DELETE", "/conversations/{conversation_id}"),
    (
        conversations.update_conversation_title,
        schemas.ConversationResponse,
        "PATCH",
        "/conversations/{conversation_id}/title",
    ),
    (
        conversations.update_conversation_config,
        schemas.ConversationResponse,
        "PATCH",
        "/conversations/{conversation_id}/config",
    ),
    (
        conversations.update_conversation_mode,
        schemas.ConversationResponse,
        "PATCH",
        "/conversations/{conversation_id}/mode",
    ),
    (
        conversations.generate_conversation_title,
        schemas.ConversationResponse,
        "POST",
        "/conversations/{conversation_id}/generate-title",
    ),
    (
        conversations.generate_summary,
        schemas.ConversationResponse,
        "POST",
        "/conversations/{conversation_id}/summary",
    ),
    (
        conversations.fork_conversation,
        dict[str, Any],
        "POST",
        "/conversations/{conversation_id}/fork",
    ),
    (
        conversations.edit_message,
        dict[str, Any],
        "PUT",
        "/conversations/{conversation_id}/messages/{message_id}",
    ),
    (
        conversations.request_tool_undo,
        dict[str, Any],
        "POST",
        "/conversations/{conversation_id}/tools/{execution_id}/undo",
    ),
    (
        participants.list_participants,
        participants.RosterResponse,
        "GET",
        "/conversations/{conversation_id}/participants",
    ),
    (
        participants.add_participant,
        participants.RosterResponse,
        "POST",
        "/conversations/{conversation_id}/participants",
    ),
    (
        participants.remove_participant,
        participants.RosterResponse,
        "DELETE",
        "/conversations/{conversation_id}/participants/{agent_id}",
    ),
    (
        participants.set_coordinator,
        participants.RosterResponse,
        "PATCH",
        "/conversations/{conversation_id}/participants/coordinator",
    ),
    (
        participants.set_focused_agent,
        participants.RosterResponse,
        "PATCH",
        "/conversations/{conversation_id}/participants/focused",
    ),
    (
        participants.list_mention_candidates,
        participants.MentionCandidatesResponse,
        "GET",
        "/conversations/{conversation_id}/mention-candidates",
    ),
    (
        messages.get_conversation_messages,
        dict[str, Any],
        "GET",
        "/conversations/{conversation_id}/messages",
    ),
    (
        messages.get_conversation_execution,
        dict[str, Any],
        "GET",
        "/conversations/{conversation_id}/execution",
    ),
    (
        messages.get_conversation_tool_executions,
        dict[str, Any],
        "GET",
        "/conversations/{conversation_id}/tool-executions",
    ),
    (
        messages.get_conversation_execution_status,
        dict[str, Any],
        "GET",
        "/conversations/{conversation_id}/status",
    ),
    (
        messages.get_execution_stats,
        schemas.ExecutionStatsResponse,
        "GET",
        "/conversations/{conversation_id}/execution/stats",
    ),
    (
        messages.get_message_replies,
        list[dict[str, Any]],
        "GET",
        "/conversations/{conversation_id}/messages/{message_id}/replies",
    ),
    (tools.list_tools, schemas.ToolsListResponse, "GET", "/tools"),
    (tools.get_tool_capabilities, schemas.CapabilitySummaryResponse, "GET", "/tools/capabilities"),
    (
        tools.list_tool_compositions,
        schemas.ToolCompositionsListResponse,
        "GET",
        "/tools/compositions",
    ),
    (
        tools.get_tool_composition,
        schemas.ToolCompositionResponse,
        "GET",
        "/tools/compositions/{composition_id}",
    ),
    (tools.debug_tool_policy, schemas.ToolPolicyDebugResponse, "POST", "/debug/tool-policy"),
    (
        patterns.list_project_shared_patterns,
        schemas.ProjectPatternsListResponse,
        "GET",
        "/workflows/patterns/project/{project_id}",
    ),
    (patterns.list_patterns, schemas.PatternsListResponse, "GET", "/workflows/patterns"),
    (
        patterns.get_pattern,
        schemas.WorkflowPatternResponse,
        "GET",
        "/workflows/patterns/{pattern_id}",
    ),
    (patterns.delete_pattern, dict[str, Any], "DELETE", "/workflows/patterns/{pattern_id}"),
    (patterns.reset_patterns, schemas.ResetPatternsResponse, "POST", "/workflows/patterns/reset"),
    (config.check_config_modify_permission, dict[str, Any], "GET", "/config/can-modify"),
    (config.get_tenant_agent_config, schemas.TenantAgentConfigResponse, "GET", "/config"),
    (
        config.get_tenant_agent_config_authority_revision,
        schemas.TenantAgentConfigAuthorityRevisionResponse,
        "GET",
        "/config/authority-revision",
    ),
    (config.get_hook_catalog, schemas.HookCatalogResponse, "GET", "/config/hooks/catalog"),
    (config.update_tenant_agent_config, schemas.TenantAgentConfigResponse, "PUT", "/config"),
    (
        hitl.get_pending_hitl_requests,
        schemas.PendingHITLResponse,
        "GET",
        "/hitl/conversations/{conversation_id}/pending",
    ),
    (
        hitl.get_project_pending_hitl_requests,
        schemas.PendingHITLResponse,
        "GET",
        "/hitl/projects/{project_id}/pending",
    ),
    (hitl.respond_to_hitl, schemas.HumanInteractionResponse, "POST", "/hitl/respond"),
    (hitl.cancel_hitl_request, schemas.HumanInteractionResponse, "POST", "/hitl/cancel"),
    (
        events.get_conversation_events,
        schemas.EventReplayResponse,
        "GET",
        "/conversations/{conversation_id}/events",
    ),
    (
        events.get_execution_status,
        schemas.ExecutionStatusResponse,
        "GET",
        "/conversations/{conversation_id}/execution-status",
    ),
    (events.resume_execution, dict[str, Any], "POST", "/conversations/{conversation_id}/resume"),
    (
        events.get_workflow_status,
        schemas.WorkflowStatusResponse,
        "GET",
        "/conversations/{conversation_id}/workflow-status",
    ),
    (templates.create_template, templates.TemplateResponse, "POST", "/templates"),
    (templates.list_templates, list[templates.TemplateResponse], "GET", "/templates"),
    (templates.get_template, templates.TemplateResponse, "GET", "/templates/{template_id}"),
    (templates.update_template, templates.TemplateResponse, "PUT", "/templates/{template_id}"),
    (templates.delete_template, None, "DELETE", "/templates/{template_id}"),
    (plans.switch_mode, plans.ModeResponse, "POST", "/plan/mode"),
    (plans.get_mode, plans.ConversationModeResponse, "GET", "/plan/mode/{conversation_id}"),
    (plans.get_tasks, plans.TaskListResponse, "GET", "/plan/tasks/{conversation_id}"),
    (plans.approve_plan_and_start, dict[str, Any], "POST", "/plans/approve-and-start"),
    (run_input.create_run_input, run_schemas.RunInputAck, "POST", "/runs/{run_id}/inputs"),
    (run_input.list_run_inputs, run_schemas.RunInputListResponse, "GET", "/runs/{run_id}/inputs"),
    (
        run_input.promote_run_input,
        run_schemas.PromoteRunInputResponse,
        "POST",
        "/runs/{run_id}/inputs/{input_id}/promote",
    ),
    (
        run_review.get_active_run,
        run_schemas.ActiveRunResponse,
        "GET",
        "/conversations/{conversation_id}/active-run",
    ),
    (
        run_review.get_latest_run,
        run_schemas.LatestRunResponse,
        "GET",
        "/conversations/{conversation_id}/latest-run",
    ),
    (run_review.get_run_summary, run_schemas.RunSummaryResponse, "GET", "/runs/{run_id}/summary"),
    (run_review.get_run_changes, run_schemas.RunChangesResponse, "GET", "/runs/{run_id}/changes"),
    (
        session.get_conversation_session_projection,
        session_schemas.ConversationSessionProjectionResponse,
        "GET",
        "/conversations/{conversation_id}/session",
    ),
    (
        subagent.cancel_subagent_execution,
        subagent.CancelSubAgentResponse,
        "POST",
        "/subagent/{execution_id}/cancel",
    ),
    (binding.create_binding, dict[str, Any], "POST", "/bindings"),
    (binding.list_bindings, list[dict[str, Any]], "GET", "/bindings"),
    (binding.delete_binding, dict[str, Any], "DELETE", "/bindings/{binding_id}"),
    (binding.set_binding_enabled, dict[str, Any], "PATCH", "/bindings/{binding_id}/enabled"),
    (binding.list_group_bindings, list[dict[str, Any]], "GET", "/bindings/groups/{group_id}"),
    (binding.test_binding_match, binding.TestBindingResponse, "POST", "/bindings/test"),
    (definitions.create_definition, dict[str, Any], "POST", "/definitions"),
    (
        definitions.list_definitions,
        list[dict[str, Any]] | definitions.DefinitionListResponse,
        "GET",
        "/definitions",
    ),
    (definitions.get_definition, dict[str, Any], "GET", "/definitions/{definition_id}"),
    (definitions.update_definition, dict[str, Any], "PUT", "/definitions/{definition_id}"),
    (definitions.delete_definition, dict[str, Any], "DELETE", "/definitions/{definition_id}"),
    (
        definitions.set_definition_enabled,
        dict[str, Any],
        "PATCH",
        "/definitions/{definition_id}/enabled",
    ),
    (
        trace.get_project_active_run_count,
        schemas.ProjectActiveRunCountResponse,
        "GET",
        "/trace/runs/project/{project_id}/active/count",
    ),
    (
        trace.list_project_runs,
        schemas.ProjectSubAgentRunListResponse,
        "GET",
        "/trace/runs/project/{project_id}",
    ),
    (
        trace.get_tenant_active_run_count,
        schemas.TenantActiveRunCountResponse,
        "GET",
        "/trace/runs/tenant/{tenant_id}/active/count",
    ),
    (
        trace.list_tenant_runs,
        schemas.TenantSubAgentRunListResponse,
        "GET",
        "/trace/runs/tenant/{tenant_id}",
    ),
    (trace.get_active_run_count, schemas.ActiveRunCountResponse, "GET", "/trace/runs/active/count"),
    (trace.list_runs, schemas.SubAgentRunListResponse, "GET", "/trace/runs/{conversation_id}"),
    (
        trace.get_trace_chain,
        schemas.TraceChainResponse,
        "GET",
        "/trace/runs/{conversation_id}/trace/{trace_id}",
    ),
    (
        trace.get_descendants,
        schemas.DescendantTreeResponse,
        "GET",
        "/trace/runs/{conversation_id}/{run_id}/descendants",
    ),
    (trace.get_run, schemas.SubAgentRunResponse, "GET", "/trace/runs/{conversation_id}/{run_id}"),
    (graph.list_graphs, graph.GraphListResponse, "GET", "/graphs"),
    (graph.create_graph, graph.GraphResponse, "POST", "/graphs"),
    (graph.get_graph, graph.GraphResponse, "GET", "/graphs/{graph_id}"),
    (graph.update_graph, graph.GraphResponse, "PUT", "/graphs/{graph_id}"),
    (graph.delete_graph, None, "DELETE", "/graphs/{graph_id}"),
    (graph.start_graph_run, graph.GraphRunResponse, "POST", "/graphs/{graph_id}/runs"),
    (graph.list_graph_runs, graph.GraphRunListResponse, "GET", "/graphs/{graph_id}/runs"),
    (graph.get_graph_run, graph.GraphRunResponse, "GET", "/graphs/runs/{run_id}"),
    (graph.cancel_graph_run, graph.GraphRunResponse, "POST", "/graphs/runs/{run_id}/cancel"),
)

_STATUS_CODES_V2: dict[Callable[..., Any], int] = {
    conversations.create_conversation: 201,
    conversations.delete_conversation: 204,
    participants.add_participant: 201,
    patterns.delete_pattern: 200,
    events.resume_execution: 202,
    templates.create_template: 201,
    templates.delete_template: 204,
    graph.create_graph: 201,
    graph.delete_graph: 204,
    graph.start_graph_run: 201,
}
_DEPRECATED_ENDPOINTS_V2 = (conversations.generate_conversation_title,)
_PLAN_ENDPOINTS_V2 = (
    plans.switch_mode,
    plans.get_mode,
    plans.get_tasks,
    plans.approve_plan_and_start,
)


def _agent_route_v2(
    endpoint: Callable[..., Any],
    response_model: object | None,
    method: str,
    path: str,
) -> RouteDefinitionV2:
    return RouteDefinitionV2(
        owner_entry_id=AGENT_HTTP_ROUTES_ENTRY_V2,
        path=f"{_AGENT_PREFIX_V2}{path}",
        methods=(method,),
        endpoint=endpoint,
        name=endpoint.__name__,
        tags=("agent", "plan") if endpoint in _PLAN_ENDPOINTS_V2 else ("agent",),
        status_code=_STATUS_CODES_V2.get(endpoint),
        response_model=response_model,
        deprecated=True if endpoint in _DEPRECATED_ENDPOINTS_V2 else None,
        replaces_builtin_row_id=AGENT_HTTP_ROUTES_ROW_V2,
    )


def agent_route_definitions_v2() -> tuple[RouteDefinitionV2, ...]:
    """Return the complete, explicitly claimed ``agent`` inventory row."""
    return tuple(_agent_route_v2(*spec) for spec in _AGENT_ROUTE_SPECS_V2)


def builtin_agent_http_routes_definition_v2() -> PluginDefinitionV2:
    """Register agent routes as reversible effects of one V2 Fiber."""
    definitions = agent_route_definitions_v2()

    async def apply(context: ContextV2, _config: Mapping[str, Any]) -> None:
        builder = context.require(ROUTE_TABLE_BUILDER_INJECT_V2)
        if not isinstance(builder, RouteTableBuilderV2):
            raise RuntimeV2Error(
                "invalid_route_table_builder",
                "route_table inject is not a protocol v2 route table builder",
            )

        async def setup() -> tuple[Callable[[], Awaitable[None]], ...]:
            disposers: list[Callable[[], Awaitable[None]]] = []
            try:
                for definition in definitions:
                    disposers.append(builder.contribute(definition))
            except Exception:
                for dispose in reversed(disposers):
                    await dispose()
                raise
            return tuple(disposers)

        await context.effect(setup, label=AGENT_HTTP_ROUTES_ENTRY_V2)

    return PluginDefinitionV2(
        module_ref=AGENT_HTTP_ROUTES_MODULE_V2,
        contract_digest=generated_contract_digest_v2(AGENT_HTTP_ROUTES_MODULE_V2),
        apply=apply,
    )


__all__ = [
    "AGENT_HTTP_ROUTES_ENTRY_V2",
    "AGENT_HTTP_ROUTES_MODULE_V2",
    "AGENT_HTTP_ROUTES_ROW_V2",
    "agent_route_definitions_v2",
    "builtin_agent_http_routes_definition_v2",
]
