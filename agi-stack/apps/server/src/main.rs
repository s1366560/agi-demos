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
//!   POST /v1/agent/run                 run a ReAct session (may suspend on HITL)
//!   POST /v1/agent/resume              answer a HITL request -> resume to completion
//!   GET  /v1/plugins                   list registered tools + enabled plugins
//!   POST /v1/plugins/enable            enable a plugin manifest (hot)
//!   POST /v1/plugins/disable           disable a plugin by name (hot)
//!   POST /v1/tools/call               invoke one tool via the ToolHost (sandboxes wasm)
//!   POST /v1/control-plane/publish     CP publishes desired tools -> DP reconcile -> ACK/NACK

use std::sync::{atomic::AtomicU64, Arc, Mutex};

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    routing::{any, get, post},
    Json, Router,
};
use serde::Deserialize;
use serde_json::{json, Value};

mod agent_ws;
mod auth;
mod enhanced_search_api;
mod graph_api;
mod identity;
mod identity_api;
mod prod_api;
mod sandbox_api;
mod shares_api;
mod skill_api;
mod trust_api;
mod workspace_api;

use agistack_adapters_docker::{DockerContainerRuntime, ImagePullPolicy};
use agistack_adapters_http_llm::{HttpEmbedding, HttpLlm};
use agistack_adapters_mem::{
    HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEmailSender,
    InMemoryEventStream, InMemoryGraphStore, InMemoryMemoryRepository, InMemoryObjectStore,
    InMemoryVectorIndex, StubLlm, SystemClock,
};
use agistack_adapters_neo4j::{connect as connect_neo4j, Neo4jGraphStore};
use agistack_adapters_postgres::{
    connect, ensure_aux_schema, PgApiKeyStore, PgCheckpointStore, PgInvitationRepository,
    PgMemoryRepository, PgProjectReadRepository, PgProjectSandboxRepository, PgProjectStore,
    PgShareRepository, PgSkillRepository, PgTenantRepository, PgTrustRepository, PgUserStore,
    PgVectorIndex, PgWorkspaceRepository,
};
use agistack_adapters_smtp::SmtpEmailSender;
use agistack_adapters_wasmtime::{WasmtimeTool, DEFAULT_FUEL, SCORE_V1_WAT};
use agistack_core::ports::{
    CheckpointStore, ContainerRuntime, EmailSender, EmbeddingPort, EventStream, GraphStore,
    LlmPort, ObjectStore, ToolHost,
};
use agistack_core::{
    Episode, Memory, MemoryService, ReActEngine, SessionState, SessionStatus, SourceType,
};
use agistack_plugin_host::{
    ConfigAck, ControlPlane, DataPlaneReconciler, HotPlugRegistry, LenTool, NativeToolFactory,
    PluginHost, PluginManifest, ToolDecl, UpperTool,
};

use crate::auth::{DevAuthenticator, PgAuthenticator, SharedAuthenticator};
use crate::identity::{
    DevIdentityService, InMemoryDeviceGrantStore, PgIdentityService, SharedDeviceGrantStore,
    SharedIdentity,
};
use crate::sandbox_api::{
    in_memory_http_service_registry, PgProjectSandboxConfigSource, ProjectSandboxService,
    SharedHttpServiceRegistry, SharedProjectSandboxes,
};
use crate::shares_api::{DevShareService, PgShareService, SharedShares};
use crate::skill_api::{DevSkillService, PgSkillService, SharedSkills};
use crate::trust_api::{DevTrustService, PgTrustService, SharedTrust};
use crate::workspace_api::{DevWorkspaceService, PgWorkspaceService, SharedWorkspaces};

/// Shared, cheaply-cloneable application state. Every `Arc`/`HotPlugRegistry`
/// field is a shared handle, so all routes operate on the same registry, memory
/// store, and control/data planes.
#[derive(Clone)]
pub(crate) struct AppState {
    pub(crate) memory: Arc<MemoryService>,
    pub(crate) engine: Arc<ReActEngine>,
    pub(crate) events: Arc<dyn EventStream>,
    pub(crate) event_counter: Arc<AtomicU64>,
    registry: HotPlugRegistry,
    plugins: Arc<PluginHost>,
    control: Arc<Mutex<ControlPlane>>,
    reconciler: Arc<Mutex<DataPlaneReconciler>>,
    /// Production authenticator backing the `/api/v1` strangled surface
    /// (Postgres in production, dev stub offline). See [`crate::auth`].
    pub(crate) auth: SharedAuthenticator,
    /// P2 identity service: login (`/auth/token`) + tenant reads. Postgres in
    /// production, dev stub offline. See [`crate::identity`].
    pub(crate) identity: SharedIdentity,
    /// P2 share service: authenticated share management plus public token access.
    pub(crate) shares: SharedShares,
    /// P2 trust governance service: policies, approval requests, and decisions.
    pub(crate) trust: SharedTrust,
    /// P5 skill store/versioning service over Python-owned `skills` tables.
    pub(crate) skills: SharedSkills,
    /// P6 workspace/task/topology/blackboard foundation over Python-owned
    /// workspace tables.
    pub(crate) workspaces: SharedWorkspaces,
    /// P4 knowledge-graph store. Server composition picks Neo4j when configured,
    /// otherwise an in-memory dev/test backend behind the same portable port.
    pub(crate) graph: Arc<dyn GraphStore>,
    /// P5 project sandbox lifecycle service over the portable ContainerRuntime
    /// port. Docker stays server-only; tests/dev can use the in-memory runtime.
    pub(crate) sandboxes: SharedProjectSandboxes,
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

// ---- wiring ---------------------------------------------------------------

/// Resolve the LLM + embedding ports from the environment — the cloud↔local
/// seam. Default is the offline stub pair so `cargo run` and tests need no
/// network or keys; setting `AGISTACK_LLM_BASE_URL` swaps in the HTTP adapter
/// (optionally `AGISTACK_LLM_MODEL`, `AGISTACK_EMBED_MODEL`, `AGISTACK_LLM_API_KEY`).
fn select_llm_and_embedding() -> (Arc<dyn LlmPort>, Arc<dyn EmbeddingPort>) {
    match std::env::var("AGISTACK_LLM_BASE_URL") {
        Ok(base) if !base.is_empty() => {
            let chat_model =
                std::env::var("AGISTACK_LLM_MODEL").unwrap_or_else(|_| "gpt-4o-mini".into());
            let embed_model = std::env::var("AGISTACK_EMBED_MODEL")
                .unwrap_or_else(|_| "text-embedding-3-small".into());
            let key = std::env::var("AGISTACK_LLM_API_KEY").ok();
            let mut llm = HttpLlm::new(base.clone(), chat_model);
            let mut emb = HttpEmbedding::new(base, embed_model);
            if let Some(k) = key {
                llm = llm.with_api_key(k.clone());
                emb = emb.with_api_key(k);
            }
            eprintln!("[agistack] LLM port: HTTP (cloud) via AGISTACK_LLM_BASE_URL");
            (Arc::new(llm), Arc::new(emb))
        }
        _ => (Arc::new(StubLlm), Arc::new(HashEmbedding::new(64))),
    }
}

fn build_registry() -> HotPlugRegistry {
    // Shared hot-pluggable registry — the single data-plane tool set used by the
    // agent, the plugin lifecycle, and the CP/DP reconciler alike.
    let registry = HotPlugRegistry::new();
    registry.register_tool(Arc::new(LenTool));
    registry.register_tool(Arc::new(UpperTool));
    // Native server tier hosts an untrusted tool in a Wasmtime sandbox (fuel +
    // epoch quotas). The same scorer `.wasm` runs under Wasmi on wasm/iOS — only
    // the host runtime differs (ADR-0002/0003). `wasmtime` is native-only and,
    // like `tokio`, never leaks back into the core or its port signatures.
    registry.register_tool(Arc::new(
        WasmtimeTool::from_wat("score", "1.0.0", SCORE_V1_WAT, DEFAULT_FUEL)
            .expect("built-in scorer WAT is valid"),
    ));
    registry
}

fn select_email_sender() -> Arc<dyn EmailSender> {
    match std::env::var("AGISTACK_SMTP_HOST") {
        Ok(host) if !host.is_empty() => {
            let sender = match (
                std::env::var("AGISTACK_SMTP_USERNAME").ok(),
                std::env::var("AGISTACK_SMTP_PASSWORD").ok(),
            ) {
                (Some(username), Some(password))
                    if !username.is_empty() && !password.is_empty() =>
                {
                    SmtpEmailSender::relay(&host, username, password)
                        .expect("configure AGISTACK_SMTP_HOST relay")
                }
                _ => {
                    let port = std::env::var("AGISTACK_SMTP_PORT")
                        .ok()
                        .and_then(|p| p.parse::<u16>().ok())
                        .unwrap_or(1025);
                    SmtpEmailSender::plaintext(&host, port)
                }
            };
            eprintln!("[agistack] email sender: SMTP via AGISTACK_SMTP_HOST");
            Arc::new(sender)
        }
        _ => {
            eprintln!("[agistack] email sender: in-memory (dev)");
            Arc::new(InMemoryEmailSender::new())
        }
    }
}

async fn build_device_grant_store() -> SharedDeviceGrantStore {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisDeviceGrantStore::connect(&url).await {
                Ok(store) => {
                    eprintln!("[agistack] device-code grants: Redis TTL via REDIS_URL");
                    Arc::new(store)
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] device-code grants: Redis unavailable ({err}); falling back to in-memory"
                    );
                    Arc::new(InMemoryDeviceGrantStore::new())
                }
            }
        }
        _ => {
            eprintln!("[agistack] device-code grants: in-memory (dev)");
            Arc::new(InMemoryDeviceGrantStore::new())
        }
    }
}

async fn build_object_store() -> Arc<dyn ObjectStore> {
    let requested = std::env::var("AGISTACK_OBJECT_STORE")
        .map(|value| value.eq_ignore_ascii_case("s3"))
        .unwrap_or(false)
        || std::env::var("AGISTACK_S3_BUCKET")
            .map(|value| !value.is_empty())
            .unwrap_or(false);
    if requested {
        let endpoint = std::env::var("AGISTACK_S3_ENDPOINT")
            .ok()
            .or_else(|| std::env::var("S3_TEST_ENDPOINT").ok());
        let region = std::env::var("AGISTACK_S3_REGION").unwrap_or_else(|_| "us-east-1".into());
        let access_key = std::env::var("AGISTACK_S3_ACCESS_KEY")
            .ok()
            .or_else(|| std::env::var("S3_TEST_ACCESS_KEY").ok())
            .unwrap_or_else(|| "minioadmin".into());
        let secret_key = std::env::var("AGISTACK_S3_SECRET_KEY")
            .ok()
            .or_else(|| std::env::var("S3_TEST_SECRET_KEY").ok())
            .unwrap_or_else(|| "minioadmin".into());
        let bucket =
            std::env::var("AGISTACK_S3_BUCKET").unwrap_or_else(|_| "agistack-objects".into());
        match agistack_adapters_s3::connect(
            endpoint.as_deref(),
            &region,
            &access_key,
            &secret_key,
            &bucket,
        )
        .await
        {
            Ok(store) => {
                eprintln!("[agistack] object store: S3/MinIO bucket {bucket}");
                return Arc::new(store);
            }
            Err(err) => {
                eprintln!(
                    "[agistack] object store: S3/MinIO unavailable ({err}); falling back to in-memory"
                );
            }
        }
    }
    eprintln!("[agistack] object store: in-memory (dev)");
    Arc::new(InMemoryObjectStore::new())
}

/// Persistence + auth selection at the composition root — the strangler switch
/// (plan.md Section 14). When `DATABASE_URL` is set, bind the production Postgres
/// tier (**the same schema Python owns**, ADR-0001) and the SHA256 `api_keys`
/// authenticator; otherwise use the zero-dependency in-memory adapters and a dev
/// authenticator so `cargo run`/tests need no database. The heavy `sqlx`/`tokio`
/// deps stay inside `adapters-postgres`; the core only ever sees `Arc<dyn _>`.
async fn build_memory_and_auth(
    llm: Arc<dyn LlmPort>,
    embedding: Arc<dyn EmbeddingPort>,
    object_store: Arc<dyn ObjectStore>,
) -> (
    Arc<MemoryService>,
    Arc<dyn CheckpointStore>,
    SharedAuthenticator,
    SharedIdentity,
    SharedShares,
    SharedTrust,
    SharedSkills,
    SharedWorkspaces,
    Option<PgProjectSandboxRepository>,
    Option<PgProjectReadRepository>,
) {
    let email = select_email_sender();
    let device_grants = build_device_grant_store().await;
    let invitation_base_url = std::env::var("AGISTACK_INVITATION_BASE_URL")
        .unwrap_or_else(|_| "http://localhost:8000".into());
    match std::env::var("DATABASE_URL") {
        Ok(url) if !url.is_empty() => {
            let pool = connect(&url)
                .await
                .expect("connect DATABASE_URL (production Postgres)");
            // Additive-only: create the Rust-owned aux tables; never alters a
            // Python-owned table (shared-DB invariant).
            ensure_aux_schema(&pool)
                .await
                .expect("ensure agistack_* auxiliary schema");

            let memory = Arc::new(
                MemoryService::new(
                    Arc::new(PgMemoryRepository::new(pool.clone())),
                    llm,
                    embedding,
                    Arc::new(SystemClock),
                )
                .with_vectors(Arc::new(PgVectorIndex::new(pool.clone()))),
            );
            let checkpoint: Arc<dyn CheckpointStore> =
                Arc::new(PgCheckpointStore::new(pool.clone()));
            // P2 identity over the same shared schema (users/api_keys/tenants).
            let identity: SharedIdentity = Arc::new(PgIdentityService::new(
                PgUserStore::new(pool.clone()),
                PgTenantRepository::new(pool.clone()),
                PgProjectReadRepository::new(pool.clone()),
                PgInvitationRepository::new(pool.clone()),
                email,
                device_grants,
                invitation_base_url,
            ));
            let authenticator: SharedAuthenticator = Arc::new(PgAuthenticator::new(
                PgApiKeyStore::new(pool.clone()),
                PgProjectStore::new(pool.clone()),
            ));
            let shares: SharedShares =
                Arc::new(PgShareService::new(PgShareRepository::new(pool.clone())));
            let trust: SharedTrust =
                Arc::new(PgTrustService::new(PgTrustRepository::new(pool.clone())));
            let skills: SharedSkills =
                Arc::new(PgSkillService::new(PgSkillRepository::new(pool.clone())));
            let workspaces: SharedWorkspaces = Arc::new(PgWorkspaceService::new(
                PgWorkspaceRepository::new(pool.clone()),
                object_store,
            ));
            let sandbox_repo = Some(PgProjectSandboxRepository::new(pool.clone()));
            let project_sandbox_config_repo = Some(PgProjectReadRepository::new(pool.clone()));
            eprintln!("[agistack] persistence: PostgreSQL (production, shared Python schema)");
            (
                memory,
                checkpoint,
                authenticator,
                identity,
                shares,
                trust,
                skills,
                workspaces,
                sandbox_repo,
                project_sandbox_config_repo,
            )
        }
        _ => {
            let memory = Arc::new(
                MemoryService::new(
                    Arc::new(InMemoryMemoryRepository::new()),
                    llm,
                    embedding,
                    Arc::new(SystemClock),
                )
                .with_vectors(Arc::new(InMemoryVectorIndex::new())),
            );
            let checkpoint: Arc<dyn CheckpointStore> = Arc::new(InMemoryCheckpointStore::new());
            let authenticator: SharedAuthenticator = Arc::new(DevAuthenticator::new("dev-user"));
            let identity: SharedIdentity = Arc::new(DevIdentityService::with_device_grants(
                "dev-user",
                device_grants,
            ));
            let shares: SharedShares = Arc::new(DevShareService::new("dev-user"));
            let trust: SharedTrust = Arc::new(DevTrustService::new("dev-user"));
            let skills: SharedSkills = Arc::new(DevSkillService::new("dev-tenant"));
            let workspaces: SharedWorkspaces = Arc::new(DevWorkspaceService::with_object_store(
                "dev-user",
                object_store,
            ));
            eprintln!("[agistack] persistence: in-memory (dev); auth: dev stub (any ms_sk_ key)");
            (
                memory,
                checkpoint,
                authenticator,
                identity,
                shares,
                trust,
                skills,
                workspaces,
                None,
                None,
            )
        }
    }
}

async fn build_event_stream() -> Arc<dyn EventStream> {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => match agistack_adapters_redis::connect(&url).await {
            Ok(stream) => {
                eprintln!("[agistack] event stream: Redis Streams via REDIS_URL");
                Arc::new(stream)
            }
            Err(err) => {
                eprintln!(
                    "[agistack] event stream: Redis unavailable ({err}); falling back to in-memory"
                );
                Arc::new(InMemoryEventStream::new())
            }
        },
        _ => {
            eprintln!("[agistack] event stream: in-memory (dev)");
            Arc::new(InMemoryEventStream::new())
        }
    }
}

async fn build_sandbox_http_service_registry() -> SharedHttpServiceRegistry {
    match std::env::var("REDIS_URL") {
        Ok(url) if !url.is_empty() => {
            match agistack_adapters_redis::RedisSandboxHttpRegistry::connect(&url).await {
                Ok(registry) => {
                    eprintln!("[agistack] sandbox HTTP services: Redis registry via REDIS_URL");
                    Arc::new(registry)
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] sandbox HTTP services: Redis unavailable ({err}); falling back to in-memory"
                    );
                    in_memory_http_service_registry()
                }
            }
        }
        _ => {
            eprintln!("[agistack] sandbox HTTP services: in-memory (dev)");
            in_memory_http_service_registry()
        }
    }
}

async fn build_graph_store() -> Arc<dyn GraphStore> {
    match std::env::var("NEO4J_URI") {
        Ok(uri) if !uri.is_empty() => {
            let user = std::env::var("NEO4J_USER").unwrap_or_else(|_| "neo4j".into());
            let password = std::env::var("NEO4J_PASSWORD").unwrap_or_else(|_| "password".into());
            match connect_neo4j(&uri, &user, &password).await {
                Ok(graph) => {
                    eprintln!("[agistack] graph store: Neo4j via NEO4J_URI");
                    Arc::new(Neo4jGraphStore::new(graph))
                }
                Err(err) => {
                    eprintln!(
                        "[agistack] graph store: Neo4j unavailable ({err}); falling back to in-memory"
                    );
                    Arc::new(InMemoryGraphStore::new())
                }
            }
        }
        _ => {
            eprintln!("[agistack] graph store: in-memory (dev)");
            Arc::new(InMemoryGraphStore::new())
        }
    }
}

async fn build_container_runtime() -> Arc<dyn ContainerRuntime> {
    let runtime = std::env::var("AGISTACK_CONTAINER_RUNTIME")
        .ok()
        .or_else(|| std::env::var("AGISTACK_SANDBOX_RUNTIME").ok())
        .unwrap_or_else(|| "memory".to_string());
    let wants_docker = runtime.eq_ignore_ascii_case("docker")
        || std::env::var("AGISTACK_DOCKER_SANDBOX")
            .map(|value| value == "1" || value.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

    if wants_docker {
        let raw_pull_policy = std::env::var("AGISTACK_SANDBOX_IMAGE_PULL").ok();
        let image_pull_policy = match raw_pull_policy.as_deref() {
            Some(raw) if !raw.trim().is_empty() => match ImagePullPolicy::parse(raw) {
                Some(policy) => policy,
                None => {
                    eprintln!(
                        "[agistack] invalid AGISTACK_SANDBOX_IMAGE_PULL={raw:?}; using if_missing"
                    );
                    ImagePullPolicy::IfMissing
                }
            },
            _ => ImagePullPolicy::IfMissing,
        };
        match DockerContainerRuntime::connect_with_image_pull_policy(image_pull_policy).await {
            Ok(runtime) => {
                eprintln!(
                    "[agistack] sandbox runtime: Docker via ContainerRuntime (image_pull={image_pull_policy})"
                );
                Arc::new(runtime)
            }
            Err(err) => {
                eprintln!(
                    "[agistack] sandbox runtime: Docker unavailable ({err}); falling back to in-memory"
                );
                Arc::new(InMemoryContainerRuntime::new())
            }
        }
    } else {
        eprintln!("[agistack] sandbox runtime: in-memory (dev)");
        Arc::new(InMemoryContainerRuntime::new())
    }
}

async fn build_state() -> AppState {
    // Cloud↔local DI switch at the composition root (Phase 3, 03 §2): when
    // `AGISTACK_LLM_BASE_URL` is set, route the LLM/embedding ports to a real
    // OpenAI-/LiteLLM-compatible endpoint (`adapters-http-llm`); otherwise use
    // the deterministic offline stubs. The core never sees which — it only holds
    // `Arc<dyn LlmPort>` / `Arc<dyn EmbeddingPort>` (ADR-0001).
    let (llm, embedding) = select_llm_and_embedding();

    let registry = build_registry();
    let object_store = build_object_store().await;

    // Persistence + auth: Postgres (production) or in-memory (dev), selected by
    // `DATABASE_URL`. This is the strangler cutover switch.
    let (
        memory,
        checkpoint,
        auth,
        identity,
        shares,
        trust,
        skills,
        workspaces,
        sandbox_repo,
        project_config_repo,
    ) = build_memory_and_auth(llm.clone(), embedding, object_store).await;
    let events = build_event_stream().await;
    let graph = build_graph_store().await;
    let sandbox_runtime = build_container_runtime().await;
    let sandbox_http_registry = build_sandbox_http_service_registry().await;
    let sandbox_image =
        std::env::var("AGISTACK_SANDBOX_IMAGE").unwrap_or_else(|_| "redis:7-alpine".to_string());
    let tool_host: Arc<dyn ToolHost> = Arc::new(registry.clone());
    let mut sandbox_service = match sandbox_repo {
        Some(repo) => ProjectSandboxService::with_postgres(sandbox_runtime, sandbox_image, repo),
        None => ProjectSandboxService::new(sandbox_runtime, sandbox_image),
    };
    if let Some(repo) = project_config_repo {
        sandbox_service = sandbox_service
            .with_project_config_source(Arc::new(PgProjectSandboxConfigSource::new(repo)));
    }
    let sandboxes = Arc::new(
        sandbox_service
            .with_http_service_registry(sandbox_http_registry)
            .with_tool_host(Arc::clone(&tool_host))
            .with_ws_mcp_connector(),
    );
    let engine = Arc::new(ReActEngine::new(
        llm,
        Arc::clone(&tool_host),
        checkpoint,
        Arc::new(SystemClock),
    ));

    let plugins = Arc::new(PluginHost::new(registry.clone()));
    let control = Arc::new(Mutex::new(ControlPlane::new()));
    let reconciler = Arc::new(Mutex::new(DataPlaneReconciler::new(registry.clone())));

    AppState {
        memory,
        engine,
        events,
        event_counter: Arc::new(AtomicU64::new(0)),
        registry,
        plugins,
        control,
        reconciler,
        auth,
        identity,
        shares,
        trust,
        skills,
        workspaces,
        graph,
        sandboxes,
    }
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

fn router(state: AppState) -> Router {
    // The production `/api/v1` surface splits by authentication:
    //   * authed — strangled memory/episodes/recall (P1) + tenant reads (P2) —
    //     sits behind the F2 auth middleware, which verifies the `ms_sk_` bearer
    //     against `api_keys` and injects a scoped `Identity`.
    //   * public — login + oauth stub (P2) — must NOT sit behind the key
    //     middleware (you can't present a key before you have one).
    // The legacy `/v1/*` demo routes stay open for local exercising.
    let authed = prod_api::router()
        .merge(enhanced_search_api::router())
        .merge(graph_api::router())
        .merge(identity_api::router_authed())
        .merge(sandbox_api::router())
        .merge(shares_api::router_authed())
        .merge(skill_api::router())
        .merge(trust_api::router_authed())
        .merge(workspace_api::router())
        .layer(axum::middleware::from_fn_with_state(
            state.clone(),
            auth::require_api_key,
        ));
    let public = identity_api::router_public().merge(shares_api::router_public());

    Router::new()
        .route("/health", get(|| async { "ok" }))
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

#[tokio::main]
async fn main() {
    let addr = std::env::var("AGISTACK_ADDR").unwrap_or_else(|_| "127.0.0.1:8088".to_string());
    let app = router(build_state().await);
    let listener = tokio::net::TcpListener::bind(&addr).await.unwrap();
    println!("agistack-server listening on http://{addr}");
    axum::serve(listener, app).await.unwrap();
}
