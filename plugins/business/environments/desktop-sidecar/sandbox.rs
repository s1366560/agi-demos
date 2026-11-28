// Compatibility endpoints for the full desktop profile.

async fn desktop_proxy() -> Html<&'static str> {
    Html(
        r#"<!doctype html><html><body style="margin:0;background:#111;color:#ddd;font:14px system-ui;display:grid;place-items:center;height:100vh"><div>Local desktop mode uses the native Electron window.</div></body></html>"#,
    )
}

async fn start_terminal(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    Json(body): Json<StartTerminalBody>,
) -> LocalJsonResult {
    ensure_active_project(&authenticated, &project_id)?;
    let run = state
        .session_store
        .run(&body.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    if run.project_id != project_id {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({ "detail": "terminal run project mismatch" })),
        ));
    }
    if run.revision != body.expected_run_revision
        || run.status != DesktopRunStatus::Running
        || run.permission_profile != DesktopPermissionProfile::FullAccess
    {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "terminal requires the exact active run revision with full_access permission",
                "actual_revision": run.revision,
                "status": run.status,
                "permission_profile": run.permission_profile,
            })),
        ));
    }
    let environment = run.environment.as_ref().ok_or_else(|| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run has no authoritative execution environment" })),
        )
    })?;
    state
        .worktree_manager()
        .validate(environment)
        .map_err(execution_environment_error)?;
    let cwd = PathBuf::from(&environment.workspace_path);
    let created_at = now_iso();
    let expires_at = (Utc::now() + ChronoDuration::seconds(30)).to_rfc3339();
    let lease = state.create_terminal_session(
        &run,
        environment,
        &authenticated,
        cwd.clone(),
        created_at,
        expires_at,
    );
    Ok(Json(json!({
        "success": true,
        "url": null,
        "port": null,
        "session_id": lease.session_id,
        "run_id": run.id,
        "run_revision": run.revision,
        "conversation_id": run.conversation_id,
        "project_id": run.project_id,
        "environment_id": environment.id,
        "created_at": lease.created_at,
        "expires_at": lease.expires_at,
        "resumable": false,
        "cwd": cwd,
        "environment": run.environment,
    })))
}

async fn terminal_ws(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    plugin_generation: Option<Extension<Arc<ActivePlatformPluginGenerationLeaseV2>>>,
    Path(project_id): Path<String>,
    Query(query): Query<TerminalSocketQuery>,
    ws: WebSocketUpgrade,
) -> Response {
    if let Err(error) = ensure_active_project(&authenticated, &project_id) {
        return error.into_response();
    }
    let Some(lease) = state.take_terminal_session(&query.session_id) else {
        return (
            StatusCode::NOT_FOUND,
            Json(json!({ "detail": "unknown or consumed terminal session" })),
        )
            .into_response();
    };
    let cwd = match validate_terminal_session_lease(&state, &authenticated, &project_id, &lease) {
        Ok(cwd) => cwd,
        Err(error) => return error.into_response(),
    };
    let state_for_socket = Arc::clone(&state);
    let authenticated_for_socket = authenticated.clone();
    let project_for_socket = project_id.clone();
    let lease_for_socket = lease.clone();
    let plugin_generation = plugin_generation.map(|Extension(generation)| generation);
    ws.protocols(["memstack.auth"])
        .on_upgrade(move |socket| {
            terminal_socket_loop(
                socket,
                cwd,
                query.session_id,
                state_for_socket,
                authenticated_for_socket,
                project_for_socket,
                lease_for_socket,
                plugin_generation,
            )
        })
        .into_response()
}

async fn sandbox_execute(
    State(_state): State<Arc<LocalRuntimeState>>,
    Json(_body): Json<Value>,
) -> LocalJsonResult {
    Err((
        StatusCode::NOT_IMPLEMENTED,
        Json(json!({
            "detail": "sandbox execution is disabled until an isolated runtime is configured"
        })),
    ))
}

async fn mcp_tools_list(State(state): State<Arc<LocalRuntimeState>>) -> Json<Value> {
    let tool_host = state.tool_host.lock().expect("local tool host").clone();
    let mut result = tool_host.mcp_tools_list_result();
    // The engine consumes tool *names* via ToolHost::list_tools; schemas are
    // served only through this listing, so the browser bridge merges its
    // metadata here under the same broker-connected gate the engine uses.
    if state.connected_browser_tool_host().is_some() {
        if let Some(tools) = result.get_mut("tools").and_then(Value::as_array_mut) {
            tools.extend(agistack_adapters_browser::list_tool_metadata());
            // Wrapper-composed tools (not part of the browser crate) advertise
            // their schemas here too.
            tools.push(browser_run_tool_host::fill_credentials_tool_metadata());
        }
    }
    Json(result)
}

async fn mcp_tools_call(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Json(body): Json<McpToolCallBody>,
) -> LocalJsonResult {
    let run = state
        .session_store
        .run(&body.run_id)
        .map_err(local_store_error)?
        .ok_or_else(|| {
            (
                StatusCode::NOT_FOUND,
                Json(json!({ "detail": "run not found" })),
            )
        })?;
    ensure_active_project(&authenticated, &run.project_id)?;
    if run.revision != body.expected_run_revision || run.status != DesktopRunStatus::Running {
        return Err((
            StatusCode::CONFLICT,
            Json(json!({
                "detail": "MCP tool execution requires the exact active run revision",
                "actual_revision": run.revision,
                "status": run.status,
            })),
        ));
    }
    let environment = run.environment.as_ref().ok_or_else(|| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": "run has no authoritative execution environment" })),
        )
    })?;
    state
        .worktree_manager()
        .validate(environment)
        .map_err(execution_environment_error)?;
    let inner = LocalToolHost::new(&environment.workspace_path)
        .map_err(|error| execution_environment_error(error.to_string()))?;
    let host = AuthorizedRunToolHost::new(Arc::new(inner), state.session_store.clone(), run);
    let input_json = serde_json::to_string(&body.arguments).map_err(|error| {
        (
            StatusCode::BAD_REQUEST,
            Json(json!({ "detail": error.to_string() })),
        )
    })?;
    let output = host.call(&body.name, &input_json).await.map_err(|error| {
        (
            StatusCode::CONFLICT,
            Json(json!({ "detail": error.to_string() })),
        )
    })?;
    let value = serde_json::from_str(&output).unwrap_or_else(|_| {
        json!({
            "isError": false,
            "content": [{ "type": "text", "text": output }],
        })
    });
    Ok(Json(value))
}
