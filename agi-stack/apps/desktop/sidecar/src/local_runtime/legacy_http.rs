//! HTTP business surface for the explicit full desktop profile.

use super::*;

pub(super) fn local_router_with_generation_required(state: Arc<LocalRuntimeState>) -> Router {
    let admission = PlatformPluginRouteAdmissionV2::required(Arc::clone(&state));
    local_router_with_generation_admission(state, admission)
}

pub(super) fn local_router_with_generation_admission(
    state: Arc<LocalRuntimeState>,
    admission: PlatformPluginRouteAdmissionV2,
) -> Router {
    let kernel_protected = Router::new()
        .route("/api/v1/auth/me", get(auth_me))
        .route("/api/v1/tenants", get(list_tenants))
        .route("/api/v1/projects", get(list_projects))
        .route("/api/v1/workspace-context", get(get_workspace_context))
        .route(
            "/api/v1/workspace-context/switch",
            post(switch_workspace_context),
        )
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_active_scope,
        ))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_user_session,
        ));

    let protected = Router::new()
        .route(
            "/api/v1/llm-providers/",
            get(list_llm_providers).post(create_llm_provider),
        )
        .route("/api/v1/llm-providers/types", get(list_llm_provider_types))
        .route(
            "/api/v1/llm-providers/models/:provider_type",
            get(list_llm_provider_models),
        )
        .route(
            "/api/v1/llm-providers/test-connection",
            post(validate_llm_provider_draft),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/tool-grants",
            get(list_workspace_tool_grants),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/tool-grants/:grant_id",
            delete(revoke_workspace_tool_grant),
        )
        .route(
            "/api/v1/browser-bridge/origin-grants",
            get(list_browser_origin_grants),
        )
        .route(
            "/api/v1/browser-bridge/origin-grants/:grant_id",
            delete(revoke_browser_origin_grant),
        )
        .route(
            "/api/v1/browser-bridge/capability-grants",
            get(list_browser_capability_grants),
        )
        .route(
            "/api/v1/browser-bridge/capability-grants/:grant_id",
            delete(revoke_browser_capability_grant),
        )
        .route(
            "/api/v1/browser-bridge/site-credentials",
            get(list_browser_site_credentials).put(upsert_browser_site_credential),
        )
        .route(
            "/api/v1/browser-bridge/site-credentials/:credential_id",
            delete(revoke_browser_site_credential),
        )
        .route(
            "/api/v1/browser-bridge/audit",
            get(list_browser_action_audit_entries),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/runtime-selection",
            put(select_llm_provider_runtime),
        )
        .route(
            "/api/v1/llm-providers/routing-policy",
            get(workspace_core_bridge::proxy_workspace_fallback)
                .put(workspace_core_bridge::proxy_workspace_fallback),
        )
        .route(
            "/api/v1/llm-providers/:provider_id",
            patch(update_llm_provider)
                .put(update_llm_provider)
                .delete(delete_llm_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/health-check",
            post(validate_llm_provider),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/models/discover",
            post(discover_llm_provider_models),
        )
        .route(
            "/api/v1/llm-providers/:provider_id/usage",
            get(get_llm_provider_usage),
        )
        .route(
            "/api/v1/projects/:project_id/my-work",
            get(list_project_my_work),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs",
            get(automation::list).post(automation::create),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/capabilities",
            get(automation::capabilities),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:automation_id",
            get(automation::get)
                .patch(automation::update)
                .delete(automation::delete),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:automation_id/toggle",
            post(automation::toggle),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:automation_id/run",
            post(automation::run),
        )
        .route(
            "/api/v1/projects/:project_id/cron-jobs/:automation_id/runs",
            get(automation::list_runs),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces",
            get(list_workspaces).post(create_workspace),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/task-sessions",
            post(task_session::create_task_session),
        )
        .route(
            "/api/v1/tenants/:tenant_id/projects/:project_id/workspaces/:workspace_id/messages",
            get(list_workspace_messages).post(create_workspace_message),
        )
        .route("/api/v1/workspaces/:workspace_id/tasks", get(list_tasks))
        .route("/api/v1/workspaces/:workspace_id/plan", get(plan_snapshot))
        .route(
            "/api/v1/agent/conversations",
            get(list_conversations).post(create_conversation),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/mode",
            patch(update_conversation_mode),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/config",
            patch(update_conversation_config),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/session",
            get(session_projection::conversation_session),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/messages",
            get(conversation_messages).post(run_conversation_message),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/messages/:message_id/model-requests/:attempt_id",
            get(model_request_replay_v2::get),
        )
        .route(
            "/api/v1/agent/plans/approve-and-start",
            post(approve_plan_and_start),
        )
        .route(
            "/api/v1/agent/conversations/:conversation_id/runs",
            get(list_conversation_runs),
        )
        .route("/api/v1/agent/runs/:run_id", get(get_run))
        .route("/api/v1/agent/runs/:run_id/changes", get(get_run_changes))
        .route(
            "/api/v1/agent/runs/:run_id/inputs",
            get(list_run_inputs).post(create_run_input),
        )
        .route(
            "/api/v1/agent/run-inputs/:input_id/promote-to-plan",
            post(promote_run_input_to_plan),
        )
        .route(
            "/api/v1/agent/runs/:run_id/pause",
            post(run_control::pause_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/resume",
            post(run_control::resume_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/fork",
            post(run_control::fork_recovery_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/cancel",
            post(run_control::cancel_run),
        )
        .route(
            "/api/v1/agent/runs/:run_id/review",
            post(run_control::review_run),
        )
        .route(
            "/api/v1/agent/artifact-versions/:artifact_version_id/review",
            post(review_artifact_version),
        )
        .route(
            "/api/v1/agent/artifact-versions/:artifact_version_id/deliver",
            post(deliver_artifact_version),
        )
        .route("/api/v1/agent/hitl/respond", post(respond_to_hitl))
        .route("/api/v1/agent/conversations/:conversation_id/browser-auth", get(browser_auth_routes::pending))
        .route("/api/v1/agent/browser-auth/:request_id/respond", post(browser_auth_routes::respond))
        .route("/api/v1/agent/plan/mode", post(switch_plan_mode))
        .route(
            "/api/v1/agent/plan/mode/:conversation_id",
            get(get_plan_mode),
        )
        .route(
            "/api/v1/agent/plan/tasks/:conversation_id",
            get(list_agent_plan_tasks),
        )
        .route("/api/v1/agent/ws", get(agent_ws))
        .route(
            "/api/v1/projects/:project_id/sandbox/desktop/proxy/",
            get(desktop_proxy),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal",
            post(start_terminal),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/terminal/proxy/ws",
            get(terminal_ws),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/execute",
            post(sandbox_execute),
        )
        .route("/mcp/tools/list", get(mcp_tools_list))
        .route("/mcp/tools/call", post(mcp_tools_call))
        .merge(platform_plugin_marketplace_v2::router())
        .merge(plugin_marketplace_v3::router())
        .merge(local_plugin_routes_v2::router())
        .merge(local_plugin_instances_v2::router())
        .merge(computer_use_v2::router())
        .merge(knowledge_authority_v2::router())
        .merge(parity_routes::router())
        .fallback(signed_project_http::dispatch)
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            workspace_core_bridge::proxy_workspace_if_authoritative,
        ))
        .layer(middleware::from_fn_with_state(
            admission,
            platform_plugin_route_admission_v2::require_generation_v2,
        ))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_active_scope,
        ))
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_user_session,
        ));

    let public_router = Router::new()
        .route("/api/v1/auth/signout", post(sign_out))
        .merge(kernel_protected)
        .merge(protected)
        .layer(middleware::from_fn_with_state(
            Arc::clone(&state),
            require_launch_capability,
        ))
        .layer(local_cors_layer())
        .with_state(Arc::clone(&state));
    public_router
        .merge(workspace_core_bridge::router(state))
        .merge(mcp_app_static::router())
}
