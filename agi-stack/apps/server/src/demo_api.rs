use axum::{
    extract::{Path, Query, State},
    http::{
        header::{ACCEPT, AUTHORIZATION, CONTENT_TYPE},
        request::Parts as RequestParts,
        HeaderValue, Method, StatusCode,
    },
    routing::{any, get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};
use tower_http::cors::{AllowOrigin, CorsLayer};

use agistack_core::{ports::ToolHost, Episode, Memory, SessionState, SessionStatus, SourceType};
use agistack_plugin_host::{ConfigAck, NativeToolFactory, PluginManifest, ToolDecl};

use crate::{
    admin_dlq_api, agent_commands_api, agent_conversations_api, agent_events_api, agent_ws,
    artifacts_api, attachments_api, audit_api, auth, billing_api, channel_api,
    conversation_session_api, cron_api, data_api, deploy_api, engines_api, enhanced_search_api,
    events_api, gene_api, graph_api, graph_stores_api, hitl_api, identity_api, instance_api,
    llm_providers_api, maintenance_api, notifications_api, prod_api, retrieval_stores_api,
    sandbox_api, schema_api, shares_api, skill_api, subagents_api, support_api, system_api,
    tenant_skill_config_api, tenant_webhooks_api, trust_api, workspace_api, AppState,
};

fn internal<E: std::fmt::Display>(e: E) -> (StatusCode, String) {
    (StatusCode::INTERNAL_SERVER_ERROR, e.to_string())
}

fn desktop_origin_allowed(origin: &HeaderValue) -> bool {
    let Ok(origin) = origin.to_str() else {
        return false;
    };
    origin == "tauri://localhost"
        || origin == "http://tauri.localhost"
        || origin == "https://tauri.localhost"
        || origin.starts_with("http://localhost:")
        || origin.starts_with("https://localhost:")
        || origin.starts_with("http://127.0.0.1:")
        || origin.starts_with("https://127.0.0.1:")
}

fn desktop_cors_layer() -> CorsLayer {
    CorsLayer::new()
        .allow_origin(AllowOrigin::predicate(
            |origin: &HeaderValue, _request_parts: &RequestParts| desktop_origin_allowed(origin),
        ))
        .allow_methods([
            Method::GET,
            Method::POST,
            Method::PUT,
            Method::PATCH,
            Method::DELETE,
            Method::OPTIONS,
        ])
        .allow_headers([ACCEPT, AUTHORIZATION, CONTENT_TYPE])
        .allow_credentials(true)
}

// ---- memory ---------------------------------------------------------------

#[derive(Deserialize)]
struct IngestRequest {
    project_id: String,
    author_id: String,
    content: String,
}

async fn ingest(
    State(app): State<AppState>,
    Json(req): Json<IngestRequest>,
) -> Result<Json<Memory>, (StatusCode, String)> {
    let episode = Episode {
        content: req.content,
        source_type: SourceType::Text,
        valid_at_ms: 0,
        name: None,
        project_id: Some(req.project_id.clone()),
        user_id: None,
    };
    app.memory
        .ingest_episode(&req.project_id, &req.author_id, &episode)
        .await
        .map(Json)
        .map_err(internal)
}

#[derive(Deserialize)]
struct SearchQuery {
    project_id: String,
    q: String,
    limit: Option<usize>,
    semantic: Option<bool>,
}

async fn search(
    State(app): State<AppState>,
    Query(q): Query<SearchQuery>,
) -> Result<Json<Vec<Memory>>, (StatusCode, String)> {
    let limit = q.limit.unwrap_or(20);
    let result = if q.semantic.unwrap_or(false) {
        app.memory.semantic_search(&q.project_id, &q.q, limit).await
    } else {
        app.memory.search(&q.project_id, &q.q, limit).await
    };
    result.map(Json).map_err(internal)
}

async fn get_memory(
    State(app): State<AppState>,
    Path(id): Path<String>,
) -> Result<Json<Memory>, (StatusCode, String)> {
    match app.memory.get(&id).await.map_err(internal)? {
        Some(m) => Ok(Json(m)),
        None => Err((StatusCode::NOT_FOUND, format!("memory not found: {id}"))),
    }
}

// ---- agent ----------------------------------------------------------------

#[derive(Deserialize)]
struct AgentRunRequest {
    session_id: String,
    goal: String,
    project_id: Option<String>,
}

/// Build a self-describing agent response that surfaces a HITL suspension
/// (`awaiting_input` + the `pending_hitl` request) alongside the full session.
fn agent_state_json(state: SessionState) -> Value {
    let awaiting = state.status == SessionStatus::AwaitingInput;
    let pending = state.pending_hitl.clone();
    json!({
        "awaiting_input": awaiting,
        "pending_hitl": pending,
        "session": state,
    })
}

async fn agent_run(
    State(app): State<AppState>,
    Json(req): Json<AgentRunRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let state = app
        .engine
        .run(&req.session_id, &req.goal, req.project_id.as_deref())
        .await
        .map_err(internal)?;
    Ok(Json(agent_state_json(state)))
}

#[derive(Deserialize)]
struct AgentResumeRequest {
    session_id: String,
    request_id: String,
    answer: String,
}

/// Resume a session suspended on a HITL request by supplying the human answer,
/// then drive it to completion (ADR-0004/0005). Idempotent and crash-safe: the
/// answer is persisted before the loop replays the suspended round.
async fn agent_resume(
    State(app): State<AppState>,
    Json(req): Json<AgentResumeRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let state = app
        .engine
        .resume(&req.session_id, &req.request_id, &req.answer)
        .await
        .map_err(internal)?;
    Ok(Json(agent_state_json(state)))
}

// ---- plugins (enable/disable lifecycle) -----------------------------------

async fn plugins_list(State(app): State<AppState>) -> Result<Json<Value>, (StatusCode, String)> {
    Ok(Json(json!({
        "tools": app.registry.names(),
        "enabled_plugins": app.plugins.enabled_plugins().map_err(internal)?,
    })))
}

async fn plugins_enable(
    State(app): State<AppState>,
    Json(manifest): Json<PluginManifest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let registered = app
        .plugins
        .enable(&manifest, &NativeToolFactory)
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
    Ok(Json(json!({
        "plugin": manifest.name,
        "registered": registered,
        "tools": app.registry.names(),
    })))
}

#[derive(Deserialize)]
struct DisableRequest {
    name: String,
}

async fn plugins_disable(
    State(app): State<AppState>,
    Json(req): Json<DisableRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let removed = app.plugins.disable(&req.name).map_err(internal)?;
    Ok(Json(json!({
        "plugin": req.name,
        "removed": removed,
        "tools": app.registry.names(),
    })))
}

// ---- control plane / data plane -------------------------------------------

#[derive(Deserialize)]
struct PublishRequest {
    tools: Vec<ToolDecl>,
}

/// The control plane publishes a new desired tool set; the data-plane reconciler
/// converges the shared registry toward it and ACK/NACKs. Mirrors an xDS push +
/// reconcile (`08-control-data-plane-separation.md`).
async fn cp_publish(
    State(app): State<AppState>,
    Json(req): Json<PublishRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let snapshot = {
        let mut cp = app.control.lock().map_err(internal)?;
        cp.publish(req.tools)
    };
    let (ack, outcome) = {
        let mut dp = app.reconciler.lock().map_err(internal)?;
        dp.reconcile(&snapshot, &NativeToolFactory)
    };
    let ack_json = match ack {
        ConfigAck::Ack { version, nonce } => {
            json!({"status":"ack","version":version,"nonce":nonce})
        }
        ConfigAck::Nack {
            version,
            nonce,
            error,
        } => {
            json!({"status":"nack","version":version,"nonce":nonce,"error":error})
        }
    };
    Ok(Json(json!({
        "ack": ack_json,
        "added": outcome.added,
        "removed": outcome.removed,
        "updated": outcome.updated,
        "tools": app.registry.names(),
    })))
}

// ---- direct tool call (exercises the native ToolHost dispatch) -------------

#[derive(Deserialize)]
struct ToolCallRequest {
    tool: String,
    input: Value,
}

/// Invoke a single tool by name through the [`ToolHost`] port. This is the path
/// that lands an untrusted call inside its sandbox: calling `score` here runs the
/// Wasmtime guest under its fuel/epoch quotas, transparently to the caller.
async fn tools_call(
    State(app): State<AppState>,
    Json(req): Json<ToolCallRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let input_json = req.input.to_string();
    let out = app
        .registry
        .call(&req.tool, &input_json)
        .await
        .map_err(|e| (StatusCode::BAD_REQUEST, e.to_string()))?;
    let output: Value = serde_json::from_str(&out).unwrap_or(Value::String(out));
    Ok(Json(json!({ "tool": req.tool, "output": output })))
}

async fn health(State(app): State<AppState>) -> &'static str {
    let _ = app
        .workspace_plan_outbox_worker
        .as_ref()
        .map(|worker| worker.handler_count());
    "ok"
}

fn legacy_routes_enabled(value: Option<&str>) -> bool {
    crate::env_flag_enabled(value)
}

fn legacy_router() -> Router<AppState> {
    Router::new()
        .route("/v1/episodes", post(ingest))
        .route("/v1/memories/search", get(search))
        .route("/v1/memories/:id", get(get_memory))
        .route("/v1/agent/run", post(agent_run))
        .route("/v1/agent/resume", post(agent_resume))
        .route("/v1/plugins", get(plugins_list))
        .route("/v1/plugins/enable", post(plugins_enable))
        .route("/v1/plugins/disable", post(plugins_disable))
        .route("/v1/tools/call", post(tools_call))
        .route("/v1/control-plane/publish", post(cp_publish))
}

pub(crate) fn router(state: AppState) -> Router {
    // The production `/api/v1` surface splits by authentication:
    //   * authed — strangled memory/episodes/recall (P1) + tenant reads (P2) —
    //     sits behind the F2 auth middleware, which verifies the `ms_sk_` bearer
    //     against `api_keys` and injects a scoped `Identity`.
    //   * public — login + oauth stub (P2) — must NOT sit behind the key
    //     middleware (you can't present a key before you have one).
    // The legacy `/v1/*` demo surface is disabled by default. It exposes
    // mutation endpoints without the production authentication middleware and
    // is available only for explicit local compatibility testing.
    let authed = prod_api::router()
        .merge(enhanced_search_api::router())
        .merge(channel_api::router())
        .merge(graph_api::router())
        .merge(agent_commands_api::router())
        .merge(agent_conversations_api::router())
        .merge(conversation_session_api::router())
        .merge(agent_events_api::router())
        .merge(events_api::router())
        .merge(audit_api::router())
        .merge(notifications_api::router())
        .merge(billing_api::router())
        .merge(support_api::router())
        .merge(system_api::router())
        .merge(maintenance_api::router())
        .merge(artifacts_api::router())
        .merge(attachments_api::router())
        .merge(admin_dlq_api::router())
        .merge(tenant_webhooks_api::router())
        .merge(schema_api::router())
        .merge(cron_api::router())
        .merge(data_api::router())
        .merge(deploy_api::router())
        .merge(instance_api::router())
        .merge(gene_api::router())
        .merge(subagents_api::router())
        .merge(graph_stores_api::router())
        .merge(retrieval_stores_api::router())
        .merge(llm_providers_api::router())
        .merge(hitl_api::router())
        .merge(identity_api::router_authed())
        .merge(sandbox_api::router())
        .merge(shares_api::router_authed())
        .merge(skill_api::router())
        .merge(tenant_skill_config_api::router())
        .merge(trust_api::router_authed())
        .merge(workspace_api::router())
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            auth::require_api_key,
        ));
    let public = engines_api::router_public()
        .merge(identity_api::router_public())
        .merge(channel_api::router_public())
        .merge(shares_api::router_public());

    let mut app = Router::new()
        .route("/health", get(health))
        .route("/api/v1/agent/ws", get(agent_ws::agent_ws))
        .merge(public)
        .merge(authed);
    if legacy_routes_enabled(
        std::env::var("AGISTACK_ENABLE_LEGACY_ROUTES")
            .ok()
            .as_deref(),
    ) {
        app = app.merge(legacy_router());
    }
    app.fallback(any(sandbox_api::preview_host_proxy))
        .layer(desktop_cors_layer())
        .with_state(state)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn desktop_origin_allowlist_accepts_tauri_and_loopback() {
        for origin in [
            "tauri://localhost",
            "http://tauri.localhost",
            "http://localhost:5173",
            "http://127.0.0.1:1420",
        ] {
            let value = HeaderValue::from_str(origin).expect("origin header");
            assert!(desktop_origin_allowed(&value), "{origin}");
        }
    }

    #[test]
    fn desktop_origin_allowlist_rejects_non_loopback_web_origins() {
        for origin in ["https://example.com", "http://192.168.1.20:5173"] {
            let value = HeaderValue::from_str(origin).expect("origin header");
            assert!(!desktop_origin_allowed(&value), "{origin}");
        }
    }

    #[test]
    fn legacy_routes_are_disabled_unless_explicitly_enabled() {
        assert!(!legacy_routes_enabled(None));
        assert!(!legacy_routes_enabled(Some("0")));
        assert!(legacy_routes_enabled(Some("1")));
        assert!(legacy_routes_enabled(Some("true")));
    }
}
