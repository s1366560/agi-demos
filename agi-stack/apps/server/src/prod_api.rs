//! Production `/api/v1` endpoints — the **P1 strangled capability** (memory,
//! episodes, recall) of the migration (plan.md Section 14.3/14.4).
//!
//! Every request/response shape here is **byte-compatible** with the Python
//! routers it replaces (`routers/memories.py`, `episodes.py`, `recall.py`) so the
//! strangler gateway can flip these paths from Python to Rust without the
//! frontend noticing:
//!   - `POST   /api/v1/memories/`        create        -> 201 [`MemoryResponse`]
//!   - `GET    /api/v1/memories/`        list+search   -> 200 [`MemoryListResponse`]
//!   - `GET    /api/v1/memories/{id}`    fetch one     -> 200 [`MemoryResponse`] / 404
//!   - `DELETE /api/v1/memories/{id}`    delete        -> 204
//!   - `POST   /api/v1/episodes/`        ingest        -> 202 [`EpisodeResponse`]
//!   - `POST   /api/v1/recall/short`     recent recall -> 200 [`ShortTermRecallResponse`]
//!
//! Handlers read the verified [`Identity`] from request extensions and **scope
//! every query by `project_id`** after an explicit access check — the
//! multi-tenancy invariant. The heavy lifting stays in the portable
//! `MemoryService`; this module is transport + Python-shape (de)serialization.

mod views;

use std::collections::{BTreeMap, BTreeSet};

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Extension, Json,
};
use serde::Deserialize;
use serde_json::{json, Value};

use agistack_core::model::{Entity, GraphEntity, Memory, Relationship};
use agistack_core::ports::RelationshipDraft;
use agistack_core::util::fnv1a;

use crate::auth::Identity;
use crate::AppState;

use views::{
    rfc3339, EpisodeResponse, MemoryListResponse, MemoryResponse, ShortTermRecallResponse,
};

const EPISODIC_GRAPH_ENTITY_TYPE: &str = "Episodic";
const EXTRACTED_GRAPH_ENTITY_TYPE: &str = "Entity";
const EPISODIC_MENTION_RELATION_TYPE: &str = "MENTIONS";
const EXTRACTED_GRAPH_RELATION_DEFAULT_TYPE: &str = "RELATED_TO";
const GRAPH_RELATIONSHIP_EXTRACTION_ENABLED_ENV: &str =
    "AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_ENABLED";
const GRAPH_RELATIONSHIP_EXTRACTION_READY_ENV: &str =
    "AGISTACK_GRAPH_RELATIONSHIP_EXTRACTION_PRODUCTION_READY";

// ---- error envelope (FastAPI `{"detail": ...}` parity) --------------------

/// A handler error rendered as `{"detail": ...}` with a status code, matching the
/// FastAPI `HTTPException` envelope the frontend already handles.
struct ApiError {
    status: StatusCode,
    detail: String,
}

impl ApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }
    fn internal(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail)
    }
    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }
    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }
    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }
}

impl IntoResponse for ApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

type ApiResult<T> = Result<T, ApiError>;

/// Verify the caller may act within `project_id`, or map to `403`/`500`.
async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> ApiResult<()> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(ApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(ApiError::forbidden("Access denied"))
    }
}

/// Verify the caller may write within `project_id`, or map to `403`/`500`.
async fn ensure_project_write(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> ApiResult<()> {
    let allowed = app
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(ApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(ApiError::forbidden("Access denied"))
    }
}

/// Verify the caller may administer `project_id`, or map to `403`/`500`.
async fn ensure_project_admin(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> ApiResult<()> {
    let allowed = app
        .auth
        .can_admin_project(&identity.user_id, project_id)
        .await
        .map_err(ApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(ApiError::forbidden("Access denied"))
    }
}

// ---- create memory --------------------------------------------------------

/// Loosely-typed entity accepted on create — mirrors the Python `EntityCreate`
/// tolerance (a dict with at least a name; `kind` or `type` for the label).
#[derive(Deserialize)]
struct EntityCreate {
    name: String,
    #[serde(default)]
    kind: Option<String>,
    #[serde(default, rename = "type")]
    type_: Option<String>,
}

/// Python `MemoryCreate` parity shape. During strangler cutover, relationship,
/// collaborator, public-visibility, and metadata fields are accepted only at
/// their Python defaults; non-default values are rejected so the gateway can keep
/// those requests on Python until the Rust endpoint persists them.
#[derive(Deserialize)]
struct MemoryCreate {
    project_id: String,
    title: String,
    content: String,
    #[serde(default = "default_content_type")]
    content_type: String,
    #[serde(default)]
    tags: Vec<String>,
    #[serde(default)]
    entities: Vec<EntityCreate>,
    #[serde(default)]
    relationships: Vec<Value>,
    #[serde(default)]
    collaborators: Vec<String>,
    #[serde(default)]
    is_public: bool,
    #[serde(default)]
    metadata: Value,
}

fn default_content_type() -> String {
    "text".to_string()
}

fn unsupported_memory_create_fields(req: &MemoryCreate) -> Vec<&'static str> {
    let mut fields = Vec::new();
    if !req.relationships.is_empty() {
        fields.push("relationships");
    }
    if !req.collaborators.is_empty() {
        fields.push("collaborators");
    }
    if req.is_public {
        fields.push("is_public");
    }
    let metadata_is_default = match &req.metadata {
        Value::Null => true,
        Value::Object(map) => map.is_empty(),
        _ => false,
    };
    if !metadata_is_default {
        fields.push("metadata");
    }
    fields
}

fn graph_extracted_entity_uuid(project_id: &str, entity: &Entity) -> String {
    let normalized_name = entity.name.trim().to_lowercase();
    let normalized_kind = match entity.kind.trim().to_lowercase() {
        kind if kind.is_empty() => EXTRACTED_GRAPH_ENTITY_TYPE.to_lowercase(),
        kind => kind,
    };
    format!(
        "entity_{:016x}",
        fnv1a(&format!(
            "{project_id}\0{normalized_kind}\0{normalized_name}"
        ))
    )
}

fn graph_mention_relationship_uuid(episode_uuid: &str, entity_uuid: &str) -> String {
    format!(
        "mentions_{:016x}",
        fnv1a(&format!("{episode_uuid}\0{entity_uuid}"))
    )
}

fn graph_extracted_relationship_uuid(
    project_id: &str,
    source_uuid: &str,
    target_uuid: &str,
    relation_type: &str,
    fact: &str,
) -> String {
    format!(
        "rel_{:016x}",
        fnv1a(&format!(
            "{project_id}\0{source_uuid}\0{target_uuid}\0{relation_type}\0{fact}"
        ))
    )
}

fn normalized_graph_entity_name(name: &str) -> String {
    name.trim().to_lowercase()
}

fn graph_relationship_relation_type(raw: &str) -> String {
    let mut out = String::new();
    let mut pending_underscore = false;
    for ch in raw.trim().chars() {
        if ch.is_ascii_alphanumeric() {
            if pending_underscore && !out.is_empty() {
                out.push('_');
            }
            out.push(ch.to_ascii_uppercase());
            pending_underscore = false;
        } else if ch == '_' || ch == '-' || ch.is_ascii_whitespace() {
            pending_underscore = true;
        }
    }
    if out.is_empty() {
        EXTRACTED_GRAPH_RELATION_DEFAULT_TYPE.to_string()
    } else if out.as_bytes()[0].is_ascii_digit() {
        format!("REL_{out}")
    } else {
        out
    }
}

fn graph_relationship_extraction_enabled() -> bool {
    graph_relationship_extraction_enabled_from_values(
        std::env::var(GRAPH_RELATIONSHIP_EXTRACTION_ENABLED_ENV)
            .ok()
            .as_deref(),
        std::env::var(GRAPH_RELATIONSHIP_EXTRACTION_READY_ENV)
            .ok()
            .as_deref(),
    )
}

fn graph_relationship_extraction_enabled_from_values(
    enabled: Option<&str>,
    ready: Option<&str>,
) -> bool {
    env_flag(enabled) && env_flag(ready)
}

fn env_flag(value: Option<&str>) -> bool {
    value
        .map(str::trim)
        .is_some_and(|value| matches!(value, "1" | "true" | "TRUE" | "True" | "yes" | "YES"))
}

fn clamped_relationship_score(score: f32) -> f32 {
    if score.is_finite() {
        score.clamp(0.0, 1.0)
    } else {
        0.0
    }
}

async fn project_memory_extraction_to_graph(
    app: &AppState,
    project_id: &str,
    memory: &Memory,
    episode_name: &str,
    episode_content: &str,
) -> agistack_core::CoreResult<()> {
    let episode_uuid = memory.id.clone();
    app.graph
        .upsert_entity(GraphEntity {
            uuid: episode_uuid.clone(),
            name: episode_name.to_string(),
            entity_type: EPISODIC_GRAPH_ENTITY_TYPE.to_string(),
            summary: episode_content.to_string(),
            project_id: project_id.to_string(),
            tenant_id: None,
            created_at_ms: memory.created_at_ms,
            name_embedding: None,
        })
        .await?;

    let mut projected_entity_ids = BTreeSet::new();
    let mut projected_entities_by_name = BTreeMap::new();
    for entity in &memory.entities {
        let name = entity.name.trim();
        if name.is_empty() {
            continue;
        }
        let entity_type = entity.kind.trim();
        let entity_type = if entity_type.is_empty() {
            EXTRACTED_GRAPH_ENTITY_TYPE
        } else {
            entity_type
        };
        let entity_uuid = graph_extracted_entity_uuid(project_id, entity);
        if !projected_entity_ids.insert(entity_uuid.clone()) {
            continue;
        }
        projected_entities_by_name
            .entry(normalized_graph_entity_name(name))
            .or_insert_with(|| entity_uuid.clone());

        app.graph
            .upsert_entity(GraphEntity {
                uuid: entity_uuid.clone(),
                name: name.to_string(),
                entity_type: entity_type.to_string(),
                summary: format!("Mentioned by {episode_name}"),
                project_id: project_id.to_string(),
                tenant_id: None,
                created_at_ms: memory.created_at_ms,
                name_embedding: None,
            })
            .await?;
        app.graph
            .upsert_relationship(Relationship {
                uuid: graph_mention_relationship_uuid(&episode_uuid, &entity_uuid),
                source_uuid: episode_uuid.clone(),
                target_uuid: entity_uuid,
                relation_type: EPISODIC_MENTION_RELATION_TYPE.to_string(),
                fact: format!("{episode_name} mentions {name}"),
                score: 1.0,
                project_id: project_id.to_string(),
                created_at_ms: memory.created_at_ms,
            })
            .await?;
    }

    if graph_relationship_extraction_enabled() && projected_entities_by_name.len() >= 2 {
        let relationships = app.memory.extract_relationships(memory).await?;
        project_memory_relationship_drafts_to_graph(
            app,
            project_id,
            memory.created_at_ms,
            &projected_entities_by_name,
            relationships,
        )
        .await?;
    }
    Ok(())
}

async fn project_memory_relationship_drafts_to_graph(
    app: &AppState,
    project_id: &str,
    created_at_ms: i64,
    projected_entities_by_name: &BTreeMap<String, String>,
    relationships: Vec<RelationshipDraft>,
) -> agistack_core::CoreResult<()> {
    let mut projected_relationship_ids = BTreeSet::new();
    for draft in relationships {
        let Some(source_uuid) =
            projected_entities_by_name.get(&normalized_graph_entity_name(&draft.source))
        else {
            continue;
        };
        let Some(target_uuid) =
            projected_entities_by_name.get(&normalized_graph_entity_name(&draft.target))
        else {
            continue;
        };
        if source_uuid == target_uuid {
            continue;
        }
        let relation_type = graph_relationship_relation_type(&draft.relation_type);
        let fact = if draft.fact.trim().is_empty() {
            format!(
                "{} {} {}",
                draft.source.trim(),
                relation_type.to_lowercase().replace('_', " "),
                draft.target.trim()
            )
        } else {
            draft.fact.trim().to_string()
        };
        let uuid = graph_extracted_relationship_uuid(
            project_id,
            source_uuid,
            target_uuid,
            &relation_type,
            &fact,
        );
        if !projected_relationship_ids.insert(uuid.clone()) {
            continue;
        }
        app.graph
            .upsert_relationship(Relationship {
                uuid,
                source_uuid: source_uuid.clone(),
                target_uuid: target_uuid.clone(),
                relation_type,
                fact,
                score: clamped_relationship_score(draft.score),
                project_id: project_id.to_string(),
                created_at_ms,
            })
            .await?;
    }
    Ok(())
}

async fn create_memory(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<MemoryCreate>,
) -> ApiResult<Response> {
    let unsupported = unsupported_memory_create_fields(&req);
    if !unsupported.is_empty() {
        return Err(ApiError::bad_request(format!(
            "Fields not yet supported on this endpoint: {}",
            unsupported.join(", ")
        )));
    }

    ensure_project_write(&app, &identity, &req.project_id).await?;

    let entities = req
        .entities
        .into_iter()
        .map(|e| Entity {
            name: e.name,
            kind: e.kind.or(e.type_).unwrap_or_default(),
        })
        .collect();

    let memory = app
        .memory
        .create_memory(
            &req.project_id,
            &identity.user_id,
            &req.title,
            &req.content,
            &req.content_type,
            req.tags,
            entities,
        )
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;

    Ok((StatusCode::CREATED, Json(MemoryResponse::from(memory))).into_response())
}

// ---- list memories --------------------------------------------------------

#[derive(Deserialize)]
struct ListQuery {
    project_id: String,
    #[serde(default = "default_page")]
    page: usize,
    #[serde(default = "default_page_size")]
    page_size: usize,
    #[serde(default)]
    search: Option<String>,
}

fn default_page() -> usize {
    1
}
fn default_page_size() -> usize {
    20
}

async fn list_memories(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(q): Query<ListQuery>,
) -> ApiResult<Json<MemoryListResponse>> {
    ensure_project_access(&app, &identity, &q.project_id).await?;

    let page = q.page.max(1);
    let page_size = q.page_size.clamp(1, 100);
    let offset = (page - 1) * page_size;
    let search = q.search.as_deref().filter(|s| !s.is_empty());

    let total = app
        .memory
        .count(&q.project_id, search)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;

    let memories = match search {
        Some(query) => {
            // Search returns newest-first, already project-scoped; page in-handler.
            let hits = app
                .memory
                .search(&q.project_id, query, offset + page_size)
                .await
                .map_err(|e| ApiError::internal(e.to_string()))?;
            hits.into_iter()
                .skip(offset)
                .take(page_size)
                .collect::<Vec<_>>()
        }
        None => app
            .memory
            .list(&q.project_id, page_size, offset)
            .await
            .map_err(|e| ApiError::internal(e.to_string()))?,
    };

    Ok(Json(MemoryListResponse {
        memories: memories.into_iter().map(MemoryResponse::from).collect(),
        total,
        page,
        page_size,
    }))
}

// ---- get / delete one memory ----------------------------------------------

async fn get_memory(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(memory_id): Path<String>,
) -> ApiResult<Json<MemoryResponse>> {
    let memory = app
        .memory
        .get(&memory_id)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?
        .ok_or_else(|| ApiError::not_found("Memory not found"))?;

    ensure_project_access(&app, &identity, &memory.project_id).await?;
    Ok(Json(MemoryResponse::from(memory)))
}

async fn delete_memory(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(memory_id): Path<String>,
) -> ApiResult<Response> {
    // Resolve first so we can enforce project scope before deleting.
    let memory = app
        .memory
        .get(&memory_id)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?
        .ok_or_else(|| ApiError::not_found("Memory not found"))?;
    ensure_project_admin(&app, &identity, &memory.project_id).await?;

    app.memory
        .delete(&memory.project_id, &memory_id)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;
    Ok(StatusCode::NO_CONTENT.into_response())
}

// ---- create episode (ingest -> memory) ------------------------------------

#[derive(Deserialize)]
struct EpisodeCreate {
    #[serde(default)]
    name: Option<String>,
    content: String,
    #[serde(default)]
    project_id: Option<String>,
}

async fn create_episode(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<EpisodeCreate>,
) -> ApiResult<Response> {
    let project_id = req
        .project_id
        .clone()
        .ok_or_else(|| ApiError::bad_request("project_id is required"))?;
    ensure_project_write(&app, &identity, &project_id).await?;

    let episode = agistack_core::model::Episode {
        content: req.content.clone(),
        source_type: agistack_core::model::SourceType::Text,
        valid_at_ms: chrono::Utc::now().timestamp_millis(),
        name: req.name.clone(),
        project_id: Some(project_id.clone()),
        user_id: Some(identity.user_id.clone()),
    };

    // P1 processes synchronously (extraction + embed) then returns 202, matching
    // the Python status code while keeping the pipeline in-process. The P4 graph
    // projection is best-effort here so the already-flipped episode ingest path
    // does not gain a new hard failure mode when the graph tier is unavailable.
    let memory = app
        .memory
        .ingest_episode(&project_id, &identity.user_id, &episode)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;
    let graph_name = req.name.clone().unwrap_or_else(|| memory.title.clone());
    let _ =
        project_memory_extraction_to_graph(&app, &project_id, &memory, &graph_name, &req.content)
            .await;

    let response = EpisodeResponse {
        id: memory.id.clone(),
        name: graph_name,
        content: req.content,
        status: "completed".to_string(),
        created_at: Some(rfc3339(memory.created_at_ms)),
        message: Some("Episode ingested into memory".to_string()),
        task_id: None,
        workflow_id: None,
    };
    Ok((StatusCode::ACCEPTED, Json(response)).into_response())
}

// ---- short-term recall ----------------------------------------------------

#[derive(Deserialize)]
struct ShortTermRecallQuery {
    #[serde(default = "default_window")]
    window_minutes: i64,
    #[serde(default = "default_recall_limit")]
    limit: usize,
    #[serde(default)]
    project_id: Option<String>,
}

fn default_window() -> i64 {
    1440
}
fn default_recall_limit() -> usize {
    100
}

async fn short_term_recall(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Json(req): Json<ShortTermRecallQuery>,
) -> ApiResult<Json<ShortTermRecallResponse>> {
    // Like Python: with no resolvable project scope, return an empty window.
    let Some(project_id) = req.project_id.clone() else {
        return Ok(Json(ShortTermRecallResponse {
            results: Vec::new(),
            total: 0,
            window_minutes: req.window_minutes,
        }));
    };
    ensure_project_access(&app, &identity, &project_id).await?;

    let since_ms = chrono::Utc::now().timestamp_millis() - req.window_minutes.max(0) * 60_000;

    let recent = app
        .memory
        .list(&project_id, req.limit, 0)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;

    let results: Vec<Value> = recent
        .into_iter()
        .filter(|m| m.created_at_ms >= since_ms)
        .map(|m| {
            json!({
                "uuid": m.id,
                "name": m.title,
                "content": m.content,
                "created_at": rfc3339(m.created_at_ms),
                "metadata": {},
            })
        })
        .collect();

    Ok(Json(ShortTermRecallResponse {
        total: results.len(),
        results,
        window_minutes: req.window_minutes,
    }))
}

// ---- router ---------------------------------------------------------------

use axum::routing::{get, post};
use axum::Router;

/// The production `/api/v1` router for the strangled memory/episode/recall
/// capability. Callers layer [`crate::auth::require_api_key`] over this so every
/// handler runs with a verified [`Identity`]. Both trailing-slash and
/// non-trailing forms are registered to avoid FastAPI-style 307 redirects that
/// strip the `Authorization` header cross-origin.
pub fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/memories/", post(create_memory).get(list_memories))
        .route("/api/v1/memories", post(create_memory).get(list_memories))
        .route(
            "/api/v1/memories/:id",
            get(get_memory).delete(delete_memory),
        )
        .route("/api/v1/episodes/", post(create_episode))
        .route("/api/v1/episodes", post(create_episode))
        .route("/api/v1/recall/short", post(short_term_recall))
}

#[cfg(test)]
mod unit {
    use std::sync::{atomic::AtomicU64, Arc, Mutex};

    use agistack_adapters_mem::{
        HashEmbedding, InMemoryCheckpointStore, InMemoryContainerRuntime, InMemoryEventStream,
        InMemoryGraphStore, InMemoryMemoryRepository, InMemoryVectorIndex, StubLlm, SystemClock,
    };
    use agistack_core::ports::{CheckpointStore, EventStream, ToolHost};
    use agistack_core::{MemoryService, ReActEngine};
    use agistack_plugin_host::{ControlPlane, DataPlaneReconciler, PluginHost};

    use super::*;
    use crate::admin_access::{DevAdminAccessService, SharedAdminAccess};
    use crate::admin_dlq_api::{DevAdminDlqService, SharedAdminDlq};
    use crate::agent_conversations_api::{DevAgentConversationService, SharedAgentConversations};
    use crate::agent_events_api::{DevAgentEventReplayService, SharedAgentEvents};
    use crate::artifacts_api::{DevArtifactService, SharedArtifacts};
    use crate::attachments_api::{DevAttachmentService, SharedAttachments};
    use crate::audit_api::{DevAuditLogService, SharedAuditLogs};
    use crate::auth::{DevAuthenticator, SharedAuthenticator};
    use crate::billing_api::{DevBillingService, SharedBilling};
    use crate::channel_api::{DevChannelService, SharedChannels};
    use crate::cron_api::{DevCronJobService, SharedCronJobs};
    use crate::data_api::{DevDataStatsScopeService, SharedDataStats};
    use crate::deploy_api::{DevDeployService, SharedDeploys};
    use crate::events_api::{DevEventLogService, SharedEventLogs};
    use crate::gene_api::{DevGeneService, SharedGenes};
    use crate::graph_stores_api::{DevGraphStoreCatalogService, SharedGraphStores};
    use crate::hitl_api::{DevHitlResponseService, SharedHitlResponses};
    use crate::identity::{DevIdentityService, SharedIdentity};
    use crate::instance_api::{DevInstanceService, SharedInstances};
    use crate::llm_providers_api::{
        DevLlmProviderAssignmentService, DevLlmProviderCatalogService, DevLlmProviderHealthService,
        DevLlmProviderUsageService, SharedLlmProviderAssignments, SharedLlmProviderHealth,
        SharedLlmProviderUsage, SharedLlmProviders,
    };
    use crate::notifications_api::{DevNotificationService, SharedNotifications};
    use crate::retrieval_stores_api::{DevRetrievalStoreCatalogService, SharedRetrievalStores};
    use crate::sandbox_api::ProjectSandboxService;
    use crate::schema_api::{DevProjectSchemaService, SharedProjectSchema};
    use crate::shares_api::{DevShareService, SharedShares};
    use crate::skill_api::{DevSkillService, SharedSkills};
    use crate::subagents_api::{DevSubagentTemplateService, SharedSubagentTemplates};
    use crate::support_api::{DevSupportService, SharedSupport};
    use crate::tenant_skill_config_api::{DevTenantSkillConfigService, SharedTenantSkillConfigs};
    use crate::tenant_webhooks_api::{DevTenantWebhookService, SharedTenantWebhooks};
    use crate::trust_api::{DevTrustService, SharedTrust};
    use crate::workspace_api::{DevWorkspaceService, SharedWorkspaces};

    fn identity() -> Identity {
        Identity {
            user_id: "dev-user".to_string(),
            _api_key_id: "dev-key".to_string(),
        }
    }

    fn test_state() -> AppState {
        let registry = crate::build_registry();
        let llm = Arc::new(StubLlm);
        let checkpoint: Arc<dyn CheckpointStore> = Arc::new(InMemoryCheckpointStore::new());
        let tool_host: Arc<dyn ToolHost> = Arc::new(registry.clone());
        let memory = Arc::new(
            MemoryService::new(
                Arc::new(InMemoryMemoryRepository::new()),
                llm.clone(),
                Arc::new(HashEmbedding::new(64)),
                Arc::new(SystemClock),
            )
            .with_vectors(Arc::new(InMemoryVectorIndex::new())),
        );
        let auth: SharedAuthenticator = Arc::new(DevAuthenticator::new("dev-user"));
        let identity_svc: SharedIdentity = Arc::new(DevIdentityService::new("dev-user"));
        let shares: SharedShares = Arc::new(DevShareService::new("dev-user"));
        let trust: SharedTrust = Arc::new(DevTrustService::new("dev-user"));
        let admin_access: SharedAdminAccess = Arc::new(DevAdminAccessService::new("dev-user"));
        let skills: SharedSkills = Arc::new(DevSkillService::new("dev-tenant"));
        let tenant_skill_configs: SharedTenantSkillConfigs =
            Arc::new(DevTenantSkillConfigService::new("dev-tenant"));
        let workspaces: SharedWorkspaces = Arc::new(DevWorkspaceService::new("dev-user"));
        let channels: SharedChannels = Arc::new(DevChannelService::new());
        let events: Arc<dyn EventStream> = Arc::new(InMemoryEventStream::new());
        let agent_events: SharedAgentEvents =
            Arc::new(DevAgentEventReplayService::new(Arc::clone(&events)));
        let agent_conversations: SharedAgentConversations =
            Arc::new(DevAgentConversationService::new(Arc::clone(&events)));
        let event_logs: SharedEventLogs = Arc::new(DevEventLogService::default());
        let audit_logs: SharedAuditLogs = Arc::new(DevAuditLogService::default());
        let notifications: SharedNotifications = Arc::new(DevNotificationService::default());
        let billing: SharedBilling = Arc::new(DevBillingService::default());
        let support: SharedSupport = Arc::new(DevSupportService::default());
        let artifacts: SharedArtifacts = Arc::new(DevArtifactService::default());
        let attachments: SharedAttachments = Arc::new(DevAttachmentService::default());
        let admin_dlq: SharedAdminDlq = Arc::new(DevAdminDlqService::empty("dev-user"));
        let llm_providers: SharedLlmProviders = Arc::new(DevLlmProviderCatalogService::default());
        let llm_provider_health: SharedLlmProviderHealth =
            Arc::new(DevLlmProviderHealthService::default());
        let llm_provider_assignments: SharedLlmProviderAssignments =
            Arc::new(DevLlmProviderAssignmentService::default());
        let llm_provider_usage: SharedLlmProviderUsage = Arc::new(DevLlmProviderUsageService);
        let tenant_webhooks: SharedTenantWebhooks = Arc::new(DevTenantWebhookService::default());
        let project_schema: SharedProjectSchema = Arc::new(DevProjectSchemaService::default());
        let cron_jobs: SharedCronJobs = Arc::new(DevCronJobService::default());
        let data_stats: SharedDataStats = Arc::new(DevDataStatsScopeService::default());
        let deploys: SharedDeploys = Arc::new(DevDeployService::default());
        let subagent_templates: SharedSubagentTemplates =
            Arc::new(DevSubagentTemplateService::default());
        let instances: SharedInstances = Arc::new(DevInstanceService::default());
        let genes: SharedGenes = Arc::new(DevGeneService::default());
        let graph_stores: SharedGraphStores =
            Arc::new(DevGraphStoreCatalogService::new("dev-tenant"));
        let retrieval_stores: SharedRetrievalStores =
            Arc::new(DevRetrievalStoreCatalogService::new("dev-tenant"));
        let hitl: SharedHitlResponses = Arc::new(DevHitlResponseService::new(Arc::clone(&events)));

        AppState {
            memory,
            engine: Arc::new(ReActEngine::new(
                llm,
                tool_host,
                checkpoint,
                Arc::new(SystemClock),
            )),
            events,
            agent_event_writer: None,
            event_counter: Arc::new(AtomicU64::new(0)),
            registry: registry.clone(),
            plugins: Arc::new(PluginHost::new(registry.clone())),
            control: Arc::new(Mutex::new(ControlPlane::new())),
            reconciler: Arc::new(Mutex::new(DataPlaneReconciler::new(registry))),
            auth,
            identity: identity_svc,
            shares,
            trust,
            admin_access,
            skills,
            skill_evolution_worker: None,
            tenant_skill_configs,
            workspaces,
            channels,
            channel_outbox_delivery_worker: None,
            hitl,
            agent_events,
            agent_conversations,
            event_logs,
            audit_logs,
            notifications,
            billing,
            support,
            artifacts,
            attachments,
            admin_dlq,
            llm_providers,
            llm_provider_health,
            llm_provider_assignments,
            llm_provider_usage,
            tenant_webhooks,
            project_schema,
            cron_jobs,
            cron_scheduler: None,
            data_stats,
            deploys,
            subagent_templates,
            instances,
            genes,
            graph_stores,
            retrieval_stores,
            workspace_plan_outbox_worker: None,
            graph: Arc::new(InMemoryGraphStore::new()),
            sandboxes: Arc::new(ProjectSandboxService::new(
                Arc::new(InMemoryContainerRuntime::new()),
                "redis:7-alpine",
            )),
        }
    }

    #[test]
    fn rfc3339_is_iso_utc() {
        // 2023-11-14T22:13:20Z
        assert_eq!(rfc3339(1_700_000_000_000), "2023-11-14T22:13:20Z");
        // Non-panicking on 0 / negative.
        assert_eq!(rfc3339(0), "1970-01-01T00:00:00Z");
    }

    #[test]
    fn memory_response_fills_python_defaults() {
        let m = Memory {
            id: "m1".into(),
            project_id: "p1".into(),
            title: "t".into(),
            content: "c".into(),
            author_id: "u1".into(),
            content_type: "text".into(),
            tags: vec!["a".into()],
            entities: vec![Entity {
                name: "Rust".into(),
                kind: "lang".into(),
            }],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1_700_000_000_000,
            embedding: None,
        };
        let v = serde_json::to_value(MemoryResponse::from(m)).unwrap();
        assert_eq!(v["processing_status"], "COMPLETED");
        assert_eq!(v["relationships"], json!([]));
        assert_eq!(v["collaborators"], json!([]));
        assert_eq!(v["is_public"], json!(false));
        assert_eq!(v["metadata"], json!({}));
        assert_eq!(v["updated_at"], Value::Null);
        assert_eq!(v["entities"][0]["name"], "Rust");
        assert_eq!(v["created_at"], "2023-11-14T22:13:20Z");
    }

    #[test]
    fn memory_create_accepts_unsupported_fields_only_at_defaults() {
        let req: MemoryCreate = serde_json::from_value(json!({
            "project_id": "p1",
            "title": "t",
            "content": "c",
            "relationships": [],
            "collaborators": [],
            "is_public": false,
            "metadata": {}
        }))
        .unwrap();
        assert!(unsupported_memory_create_fields(&req).is_empty());

        let req: MemoryCreate = serde_json::from_value(json!({
            "project_id": "p1",
            "title": "t",
            "content": "c",
            "metadata": null
        }))
        .unwrap();
        assert!(unsupported_memory_create_fields(&req).is_empty());
    }

    #[test]
    fn memory_create_rejects_unsupported_non_defaults() {
        let req: MemoryCreate = serde_json::from_value(json!({
            "project_id": "p1",
            "title": "t",
            "content": "c",
            "relationships": [{"type": "related"}],
            "collaborators": ["u2"],
            "is_public": true,
            "metadata": {"source": "sdk"}
        }))
        .unwrap();
        assert_eq!(
            unsupported_memory_create_fields(&req),
            vec!["relationships", "collaborators", "is_public", "metadata"]
        );
    }

    #[tokio::test]
    async fn create_episode_persists_episodic_graph_node() {
        let app = test_state();
        if let Err(err) = create_episode(
            State(app.clone()),
            Extension(identity()),
            Json(EpisodeCreate {
                name: Some("First episode".to_string()),
                content: "Browser durable episode state".to_string(),
                project_id: Some("p1".to_string()),
            }),
        )
        .await
        {
            panic!("episode ingest failed: {}", err.detail);
        }

        let hits = app
            .graph
            .search_entities("p1", "First episode", 10)
            .await
            .unwrap();
        assert_eq!(hits.len(), 1);
        assert_eq!(hits[0].entity_type, EPISODIC_GRAPH_ENTITY_TYPE);
        assert_eq!(hits[0].project_id, "p1");
        assert_eq!(hits[0].summary, "Browser durable episode state");
    }

    #[tokio::test]
    async fn episode_graph_projection_persists_extracted_entities_and_mentions_edges() {
        let app = test_state();
        let memory = Memory {
            id: "mem_graph_projection".into(),
            project_id: "p1".into(),
            title: "Rust graph projection".into(),
            content: "Rust projects extracted entities into the graph".into(),
            author_id: "dev-user".into(),
            content_type: "text".into(),
            tags: vec!["rust".into()],
            entities: vec![
                Entity {
                    name: "Rust".into(),
                    kind: "Language".into(),
                },
                Entity {
                    name: "Rust".into(),
                    kind: "Language".into(),
                },
                Entity {
                    name: "GraphStore".into(),
                    kind: "Component".into(),
                },
            ],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1_700_000_000_000,
            embedding: None,
        };

        project_memory_extraction_to_graph(
            &app,
            "p1",
            &memory,
            "Rust graph projection",
            "Rust projects extracted entities into the graph",
        )
        .await
        .unwrap();

        let episode = app
            .graph
            .get_entity("p1", "mem_graph_projection")
            .await
            .unwrap()
            .expect("episode graph node should be projected");
        assert_eq!(episode.entity_type, EPISODIC_GRAPH_ENTITY_TYPE);

        let rust_entity = Entity {
            name: "Rust".into(),
            kind: "Language".into(),
        };
        let rust_uuid = graph_extracted_entity_uuid("p1", &rust_entity);
        let rust = app
            .graph
            .get_entity("p1", &rust_uuid)
            .await
            .unwrap()
            .expect("extracted entity should be projected");
        assert_eq!(rust.name, "Rust");
        assert_eq!(rust.entity_type, "Language");

        let projected = app
            .graph
            .subgraph("p1", "mem_graph_projection", 1)
            .await
            .unwrap();
        let mentions: Vec<_> = projected
            .relationships
            .iter()
            .filter(|rel| rel.source_uuid == "mem_graph_projection")
            .filter(|rel| rel.relation_type == EPISODIC_MENTION_RELATION_TYPE)
            .collect();
        assert_eq!(mentions.len(), 2);
        assert!(mentions.iter().any(|rel| rel.target_uuid == rust_uuid));
    }

    #[test]
    fn graph_relationship_extraction_gate_requires_enabled_and_ready() {
        assert!(!graph_relationship_extraction_enabled_from_values(
            None, None
        ));
        assert!(!graph_relationship_extraction_enabled_from_values(
            Some("true"),
            None
        ));
        assert!(!graph_relationship_extraction_enabled_from_values(
            None,
            Some("true")
        ));
        assert!(graph_relationship_extraction_enabled_from_values(
            Some("true"),
            Some("1")
        ));
    }

    #[test]
    fn graph_relationship_relation_type_is_structural_and_neo4j_safe() {
        assert_eq!(graph_relationship_relation_type("builds-on"), "BUILDS_ON");
        assert_eq!(graph_relationship_relation_type("  "), "RELATED_TO");
        assert_eq!(
            graph_relationship_relation_type("2026 plan"),
            "REL_2026_PLAN"
        );
    }

    #[tokio::test]
    async fn relationship_drafts_project_entity_edges_when_enabled_path_supplies_drafts() {
        let app = test_state();
        let memory = Memory {
            id: "mem_relationship_projection".into(),
            project_id: "p1".into(),
            title: "Rust graph relationship projection".into(),
            content: "Rust uses GraphStore for memory relationships".into(),
            author_id: "dev-user".into(),
            content_type: "text".into(),
            tags: vec!["rust".into()],
            entities: vec![
                Entity {
                    name: "Rust".into(),
                    kind: "Language".into(),
                },
                Entity {
                    name: "GraphStore".into(),
                    kind: "Component".into(),
                },
            ],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1_700_000_000_000,
            embedding: None,
        };
        project_memory_extraction_to_graph(
            &app,
            "p1",
            &memory,
            "Rust graph relationship projection",
            "Rust uses GraphStore for memory relationships",
        )
        .await
        .unwrap();

        let rust = Entity {
            name: "Rust".into(),
            kind: "Language".into(),
        };
        let graph_store = Entity {
            name: "GraphStore".into(),
            kind: "Component".into(),
        };
        let rust_uuid = graph_extracted_entity_uuid("p1", &rust);
        let graph_store_uuid = graph_extracted_entity_uuid("p1", &graph_store);
        let mut projected_entities_by_name = BTreeMap::new();
        projected_entities_by_name.insert("rust".to_string(), rust_uuid.clone());
        projected_entities_by_name.insert("graphstore".to_string(), graph_store_uuid.clone());

        project_memory_relationship_drafts_to_graph(
            &app,
            "p1",
            memory.created_at_ms,
            &projected_entities_by_name,
            vec![
                RelationshipDraft {
                    source: "Rust".into(),
                    target: "GraphStore".into(),
                    relation_type: "builds-on".into(),
                    fact: "Rust uses GraphStore for memory relationships".into(),
                    score: 1.4,
                },
                RelationshipDraft {
                    source: "Rust".into(),
                    target: "Unknown".into(),
                    relation_type: "IGNORED".into(),
                    fact: "ignored unknown endpoint".into(),
                    score: 0.5,
                },
            ],
        )
        .await
        .unwrap();

        let projected = app.graph.subgraph("p1", &rust_uuid, 1).await.unwrap();
        let extracted: Vec<_> = projected
            .relationships
            .iter()
            .filter(|rel| rel.source_uuid == rust_uuid)
            .filter(|rel| rel.target_uuid == graph_store_uuid)
            .filter(|rel| rel.relation_type == "BUILDS_ON")
            .collect();
        assert_eq!(extracted.len(), 1);
        assert_eq!(
            extracted[0].fact,
            "Rust uses GraphStore for memory relationships"
        );
        assert_eq!(extracted[0].score, 1.0);
    }

    // ---- F3 parity gate: assert the P1 wire shapes against contract-derived
    // goldens in `apps/server/tests/golden/` (plan.md §14.2 F3).

    fn sample_memory() -> Memory {
        Memory {
            id: "11111111-1111-4111-8111-111111111111".into(),
            project_id: "22222222-2222-4222-8222-222222222222".into(),
            title: "Portable core".into(),
            content: "Rust compiles to every target.".into(),
            author_id: "33333333-3333-4333-8333-333333333333".into(),
            content_type: "text".into(),
            tags: vec!["rust".into(), "wasm".into()],
            entities: vec![Entity {
                name: "Rust".into(),
                kind: "lang".into(),
            }],
            version: 1,
            status: "ENABLED".into(),
            created_at_ms: 1_700_000_000_000, // 2023-11-14T22:13:20Z
            embedding: None,
        }
    }

    #[test]
    fn memory_response_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/memory_response.json")).unwrap();
        let actual = serde_json::to_value(MemoryResponse::from(sample_memory())).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn episode_response_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/episode_response.json")).unwrap();
        // Built exactly as `create_episode` builds it (deterministic inputs).
        let resp = EpisodeResponse {
            id: "11111111-1111-4111-8111-111111111111".into(),
            name: "First episode".into(),
            content: "hello world".into(),
            status: "completed".into(),
            created_at: Some(rfc3339(1_700_000_000_000)),
            message: Some("Episode ingested into memory".into()),
            task_id: None,
            workflow_id: None,
        };
        let actual = serde_json::to_value(&resp).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }

    #[test]
    fn short_term_recall_matches_golden() {
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/short_term_recall.json")).unwrap();
        // Mirror the handler's per-memory projection so the shape under test is
        // the one the endpoint actually serves.
        let m = sample_memory();
        let results: Vec<Value> = vec![json!({
            "uuid": m.id,
            "name": m.title,
            "content": m.content,
            "created_at": rfc3339(m.created_at_ms),
            "metadata": {},
        })];
        let resp = ShortTermRecallResponse {
            total: results.len(),
            results,
            window_minutes: 1440,
        };
        let actual = serde_json::to_value(&resp).unwrap();
        agistack_parity::assert_parity(&golden, &actual);
    }
}
