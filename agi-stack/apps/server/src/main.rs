//! `agistack-server`: the native (server-tier) binary.
//!
//! It wires the runtime-agnostic [`MemoryService`] and [`ReActEngine`] to the
//! server-tier adapters (here the in-memory adapters for a zero-dependency demo;
//! swap in `agistack-adapters-device` or a future Postgres adapter without
//! touching the core) and the hot-pluggable [`HotPlugRegistry`], then exposes the
//! whole surface over HTTP.
//!
//! `tokio` lives **only** here. Everything it depends on — core, plugin-host,
//! adapters — is runtime-agnostic, which is exactly what lets the same code also
//! compile to wasm / iOS / Android behind a different shell.
//!
//! Routes:
//!   GET  /health
//!   POST /v1/episodes                  ingest an episode -> memory
//!   GET  /v1/memories/search           keyword (or ?semantic=true) search
//!   GET  /v1/memories/:id              fetch one memory
//!   POST /v1/agent/run                 run/resume a ReAct session over the registry
//!   GET  /v1/plugins                   list registered tools + enabled plugins
//!   POST /v1/plugins/enable            enable a plugin manifest (hot)
//!   POST /v1/plugins/disable           disable a plugin by name (hot)
//!   POST /v1/control-plane/publish     CP publishes desired tools -> DP reconcile -> ACK/NACK

use std::sync::{Arc, Mutex};

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    routing::{get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

use agistack_adapters_mem::{
    HashEmbedding, InMemoryCheckpointStore, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm,
    SystemClock,
};
use agistack_core::ports::ToolHost;
use agistack_core::{Episode, Memory, MemoryService, ReActEngine, SourceType};
use agistack_plugin_host::{
    ConfigAck, ControlPlane, DataPlaneReconciler, HotPlugRegistry, LenTool, NativeToolFactory,
    PluginHost, PluginManifest, ToolDecl, UpperTool,
};

/// Shared, cheaply-cloneable application state. Every `Arc`/`HotPlugRegistry`
/// field is a shared handle, so all routes operate on the same registry, memory
/// store, and control/data planes.
#[derive(Clone)]
struct AppState {
    memory: Arc<MemoryService>,
    engine: Arc<ReActEngine>,
    registry: HotPlugRegistry,
    plugins: Arc<PluginHost>,
    control: Arc<Mutex<ControlPlane>>,
    reconciler: Arc<Mutex<DataPlaneReconciler>>,
}

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

async fn agent_run(
    State(app): State<AppState>,
    Json(req): Json<AgentRunRequest>,
) -> Result<Json<Value>, (StatusCode, String)> {
    let state = app
        .engine
        .run(&req.session_id, &req.goal, req.project_id.as_deref())
        .await
        .map_err(internal)?;
    // SessionState is Serialize; wrap it so the response is self-describing.
    Ok(Json(json!({ "session": state })))
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
        ConfigAck::Ack { version, nonce } => json!({"status":"ack","version":version,"nonce":nonce}),
        ConfigAck::Nack { version, nonce, error } => {
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

// ---- wiring ---------------------------------------------------------------

fn build_state() -> AppState {
    // Shared hot-pluggable registry — the single data-plane tool set used by the
    // agent, the plugin lifecycle, and the CP/DP reconciler alike.
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(LenTool));
    registry.register_tool(Arc::new(UpperTool));

    let memory = Arc::new(
        MemoryService::new(
            Arc::new(InMemoryMemoryRepository::new()),
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(64)),
            Arc::new(SystemClock),
        )
        .with_vectors(Arc::new(InMemoryVectorIndex::new())),
    );

    let tool_host: Arc<dyn ToolHost> = Arc::new(registry.clone());
    let engine = Arc::new(ReActEngine::new(
        Arc::new(StubLlm),
        tool_host,
        Arc::new(InMemoryCheckpointStore::new()),
        Arc::new(SystemClock),
    ));

    let plugins = Arc::new(PluginHost::new(registry.clone()));
    let control = Arc::new(Mutex::new(ControlPlane::new()));
    let reconciler = Arc::new(Mutex::new(DataPlaneReconciler::new(registry.clone())));

    AppState {
        memory,
        engine,
        registry,
        plugins,
        control,
        reconciler,
    }
}

fn router(state: AppState) -> Router {
    Router::new()
        .route("/health", get(|| async { "ok" }))
        .route("/v1/episodes", post(ingest))
        .route("/v1/memories/search", get(search))
        .route("/v1/memories/:id", get(get_memory))
        .route("/v1/agent/run", post(agent_run))
        .route("/v1/plugins", get(plugins_list))
        .route("/v1/plugins/enable", post(plugins_enable))
        .route("/v1/plugins/disable", post(plugins_disable))
        .route("/v1/control-plane/publish", post(cp_publish))
        .with_state(state)
}

#[tokio::main]
async fn main() {
    let addr = std::env::var("AGISTACK_ADDR").unwrap_or_else(|_| "127.0.0.1:8088".to_string());
    let app = router(build_state());
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!("agistack-server listening on http://{addr}");
    axum::serve(listener, app).await.unwrap();
}
