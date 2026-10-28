//! Manual MCP servers use the same PKCE callback and encrypted grants as plugins.
use super::*;
use crate::local_runtime::mcp_supervisor::{
    ManualOAuthFlow, McpServerDefinition, McpServerDefinitionInput, McpTransport,
};
#[cfg(test)]
#[path = "oauth_manual_tests.rs"]
mod tests;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct QueryScope {
    project_id: String,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ActionInput {
    project_id: String,
    expected_revision: u64,
    idempotency_key: String,
    client_id: Option<String>,
    client_metadata_url: Option<String>,
    #[serde(default)]
    scopes: Vec<String>,
}

pub(in crate::local_runtime) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route("/api/v1/mcp/:server_id/oauth", get(status))
        .route("/api/v1/mcp/:server_id/oauth/:action", post(action))
}

fn server_definition(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    id: &str,
) -> PackageResult<McpServerDefinition> {
    let server = state
        .mcp_supervisor
        .server(&scope(auth), id)
        .map_err(|error| error.to_string())?
        .ok_or("oauth_server_missing")?;
    if server.transport != McpTransport::Http {
        return Err("oauth_requires_streamable_http".into());
    }
    Ok(server)
}

fn public(server_id: &str, flow: &ManualOAuthFlow, include_url: bool) -> Value {
    let mut value = json!({"server_id":server_id,"status":flow.status,"reason":flow.reason,"expires_at":flow.expires_at});
    if include_url && flow.status == "authorizing" {
        value["authorization_url"] = json!(flow.authorization_url);
    }
    value
}

fn load(
    state: &LocalRuntimeState,
    auth: &AuthenticatedContext,
    id: &str,
) -> PackageResult<ManualOAuthFlow> {
    let mut flow = state
        .mcp_supervisor
        .manual_oauth_flow(&scope(auth), id, &auth.user.user_id)?
        .unwrap_or_else(|| ManualOAuthFlow {
            status: "not_connected".into(),
            ..Default::default()
        });
    if flow.status == "authorizing"
        && (!pending(&flow.flow)
            || flow
                .expires_at
                .is_none_or(|expires| expires <= chrono::Utc::now().timestamp()))
    {
        cancel(&flow.flow);
        flow.status = "expired".into();
        flow.flow.clear();
        flow.authorization_url = None;
        flow.reason = Some("oauth_authorization_interrupted".into());
    }
    if flow.status != "authorizing" {
        let status = state
            .mcp_supervisor
            .oauth_status(id)
            .map_err(|error| error.to_string())?;
        if flow.status == "connected" || status["status"] != "not_connected" {
            flow.status = status["status"].as_str().unwrap_or("error").into();
            flow.expires_at = status["expires_at"].as_i64();
        }
    }
    Ok(flow)
}

async fn status(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path(id): Path<String>,
    Query(query): Query<QueryScope>,
) -> Response {
    ensure_project_scope(&auth, Some(&query.project_id))?;
    let _guard = MUTATION.lock().await;
    server_definition(&state, &auth, &id).map_err(fail)?;
    let flow = load(&state, &auth, &id).map_err(fail)?;
    state
        .mcp_supervisor
        .save_manual_oauth_flow(&scope(&auth), &id, &auth.user.user_id, &flow)
        .map_err(fail)?;
    Ok(Json(public(&id, &flow, false)))
}

async fn action(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(auth): Extension<AuthenticatedContext>,
    Path((id, action)): Path<(String, String)>,
    Json(input): Json<ActionInput>,
) -> Response {
    ensure_project_scope(&auth, Some(&input.project_id))?;
    ensure_managed_resource_manager(&auth)?;
    if input.idempotency_key.is_empty()
        || input.idempotency_key.len() > 128
        || input.scopes.len() > 128
        || input.scopes.iter().any(|scope| {
            scope.is_empty() || scope.len() > 256 || scope.chars().any(char::is_whitespace)
        })
    {
        return Err(fail("oauth_request_invalid"));
    }
    if !matches!(action.as_str(), "start" | "cancel" | "disconnect") {
        return Err(fail("oauth_action_invalid"));
    }
    let _guard = MUTATION.lock().await;
    let server = server_definition(&state, &auth, &id).map_err(fail)?;
    let mut flow = load(&state, &auth, &id).map_err(fail)?;
    let hash = format!("{:x}", Sha256::digest(json!({"action":action,"revision":input.expected_revision,"client_id":input.client_id,"client_metadata_url":input.client_metadata_url,"scopes":input.scopes}).to_string().as_bytes()));
    if let Some(previous) = flow
        .requests
        .get(&input.idempotency_key)
        .or_else(|| (flow.request_key == input.idempotency_key).then_some(&flow.request_hash))
    {
        if previous != &hash {
            return Err(fail("idempotency_conflict"));
        }
        return Ok(Json(public(&id, &flow, true)));
    }
    if server.revision != input.expected_revision {
        return Err(fail("oauth_server_changed"));
    }
    if flow.requests.len() >= 4096 {
        return Err(fail("oauth_request_history_full"));
    }
    flow.requests
        .insert(input.idempotency_key.clone(), hash.clone());
    if action != "start" {
        cancel(&flow.flow);
        flow.flow.clear();
        flow.authorization_url = None;
        flow.status = "not_connected".into();
        flow.expires_at = None;
        flow.reason = None;
        if action == "disconnect" {
            // Disable first: an interrupted remote revocation cannot leave a live tool surface.
            state
                .mcp_supervisor
                .update_server(
                    &scope(&auth),
                    &id,
                    McpServerDefinitionInput {
                        name: server.name,
                        description: server.description,
                        transport: server.transport,
                        command: server.command,
                        cwd: server.cwd,
                        vault_env_refs: server.vault_env_refs,
                        enabled: false,
                    },
                    server.revision,
                    &format!("manual-oauth-disconnect-{}", uuid::Uuid::new_v4()),
                )
                .map_err(fail)?;
            flow.reason = state
                .mcp_supervisor
                .oauth_disconnect(&id)
                .await
                .err()
                .map(|_| "oauth_revocation_failed".into());
        }
        flow.request_key = input.idempotency_key;
        flow.request_hash = hash;
        state
            .mcp_supervisor
            .save_manual_oauth_flow(&scope(&auth), &id, &auth.user.user_id, &flow)
            .map_err(fail)?;
        return Ok(Json(public(&id, &flow, false)));
    }
    if flow.status == "authorizing" {
        return Err(fail("oauth_authorization_already_pending"));
    }
    let resource = server
        .command
        .first()
        .cloned()
        .ok_or_else(|| fail("oauth_http_required"))?;
    let listener = tokio::net::TcpListener::bind("127.0.0.1:0")
        .await
        .map_err(|_| fail("oauth_callback_unavailable"))?;
    let redirect = format!(
        "http://127.0.0.1:{}/callback",
        listener
            .local_addr()
            .map_err(|_| fail("oauth_callback_unavailable"))?
            .port()
    );
    let declared = json!({"client_id":input.client_id,"client_metadata_url":input.client_metadata_url,"scopes":input.scopes});
    let metadata = super::super::oauth_http::discover(&resource, &declared)
        .await
        .map_err(fail)?;
    let client = super::super::oauth_http::registration(&metadata, &declared, &redirect)
        .await
        .map_err(fail)?;
    let authorization =
        Authorization::prepare(listener, &metadata, &client, &resource, true).map_err(fail)?;
    flow = ManualOAuthFlow {
        status: "authorizing".into(),
        flow: authorization.flow.clone(),
        expected_revision: server.revision,
        authorization_url: Some(authorization.url.to_string()),
        expires_at: Some(authorization.expires),
        request_key: input.idempotency_key,
        request_hash: hash,
        requests: flow.requests,
        reason: None,
    };
    state
        .mcp_supervisor
        .save_manual_oauth_flow(&scope(&auth), &id, &auth.user.user_id, &flow)
        .map_err(fail)?;
    let (sender, cancelled) = tokio::sync::oneshot::channel();
    PENDING
        .lock()
        .map_err(|_| fail("oauth_pending_unavailable"))?
        .insert(authorization.flow.clone(), sender);
    let active = Flow {
        state,
        target: FlowTarget::ManualMcp { auth },
        include_resource: true,
        server_id: id.clone(),
        flow: authorization.flow,
        csrf: authorization.csrf,
        verifier: authorization.verifier,
        redirect: authorization.redirect,
        resource,
        client,
        metadata,
    };
    tokio::spawn(callback(authorization.listener, active, cancelled));
    Ok(Json(public(&id, &flow, true)))
}

pub(super) async fn complete(
    flow: &Flow,
    auth: &AuthenticatedContext,
    code: Option<String>,
) -> PackageResult<()> {
    let _guard = MUTATION.lock().await;
    let mut pending = flow
        .state
        .mcp_supervisor
        .manual_oauth_flow(&scope(auth), &flow.server_id, &auth.user.user_id)?
        .ok_or("oauth_state_invalid")?;
    let server = server_definition(&flow.state, auth, &flow.server_id)?;
    if pending.status != "authorizing"
        || pending.flow != flow.flow
        || pending.expected_revision != server.revision
        || pending
            .expires_at
            .is_none_or(|expires| expires <= chrono::Utc::now().timestamp())
    {
        return Err("oauth_state_invalid".into());
    }
    pending.flow.clear();
    pending.authorization_url = None;
    pending.status = "error".into();
    pending.reason = Some("oauth_callback_interrupted".into());
    flow.state.mcp_supervisor.save_manual_oauth_flow(
        &scope(auth),
        &flow.server_id,
        &auth.user.user_id,
        &pending,
    )?;
    let outcome = async {
        let tokens = exchange(flow, code).await?;
        flow.state
            .mcp_supervisor
            .oauth_connect(
                &scope(auth),
                &flow.server_id,
                &flow.metadata,
                &flow.client,
                &flow.resource,
                &tokens,
            )
            .map_err(|error| error.to_string())?;
        Ok::<_, String>(())
    }
    .await;
    match &outcome {
        Ok(()) => {
            pending.status = "connected".into();
            pending.reason = None;
            pending.expires_at = flow
                .state
                .mcp_supervisor
                .oauth_status(&flow.server_id)
                .map_err(|error| error.to_string())?["expires_at"]
                .as_i64();
        }
        Err(reason) => pending.reason = Some(reason.clone()),
    }
    flow.state.mcp_supervisor.save_manual_oauth_flow(
        &scope(auth),
        &flow.server_id,
        &auth.user.user_id,
        &pending,
    )?;
    if outcome.is_ok() && server.enabled {
        let _ = flow
            .state
            .mcp_supervisor
            .list_tools(&scope(auth), &flow.server_id)
            .await;
    }
    outcome
}
