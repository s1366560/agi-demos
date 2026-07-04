use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    routing::{any, get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use agistack_core::{ports::ToolHost, Episode, Memory, SessionState, SessionStatus, SourceType};
use agistack_plugin_host::{ConfigAck, NativeToolFactory, PluginManifest, ToolDecl};

use crate::{
    agent_events_api, agent_ws, auth, channel_api, enhanced_search_api, graph_api, hitl_api,
    identity_api, prod_api, sandbox_api, shares_api, skill_api, tenant_skill_config_api, trust_api,
    workspace_api, AppState,
};

fn internal<E: std::fmt::Display>(e: E) -> (StatusCode, String) {
    (StatusCode::INTERNAL_SERVER_ERROR, e.to_string())
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

async fn plugins_list(State(app): State<AppState>) -> Json<Value> {
    Json(json!({
        "tools": app.registry.names(),
        "enabled_plugins": app.plugins.enabled_plugins(),
    }))
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
) -> Json<Value> {
    let removed = app.plugins.disable(&req.name);
    Json(json!({
        "plugin": req.name,
        "removed": removed,
        "tools": app.registry.names(),
    }))
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

pub(crate) fn router(state: AppState) -> Router {
    // The production `/api/v1` surface splits by authentication:
    //   * authed — strangled memory/episodes/recall (P1) + tenant reads (P2) —
    //     sits behind the F2 auth middleware, which verifies the `ms_sk_` bearer
    //     against `api_keys` and injects a scoped `Identity`.
    //   * public — login + oauth stub (P2) — must NOT sit behind the key
    //     middleware (you can't present a key before you have one).
    // The legacy `/v1/*` demo routes stay open for local exercising.
    let authed = prod_api::router()
        .merge(enhanced_search_api::router())
        .merge(channel_api::router())
        .merge(graph_api::router())
        .merge(agent_events_api::router())
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
    let public = identity_api::router_public().merge(shares_api::router_public());

    Router::new()
        .route("/health", get(health))
        .route("/v1/episodes", post(ingest))
        .route("/v1/memories/search", get(search))
        .route("/v1/memories/:id", get(get_memory))
        .route("/v1/agent/run", post(agent_run))
        .route("/v1/agent/resume", post(agent_resume))
        .route("/api/v1/agent/ws", get(agent_ws::agent_ws))
        .route("/v1/plugins", get(plugins_list))
        .route("/v1/plugins/enable", post(plugins_enable))
        .route("/v1/plugins/disable", post(plugins_disable))
        .route("/v1/tools/call", post(tools_call))
        .route("/v1/control-plane/publish", post(cp_publish))
        .merge(public)
        .merge(authed)
        .fallback(any(sandbox_api::preview_host_proxy))
        .with_state(state)
}
