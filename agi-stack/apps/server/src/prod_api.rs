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

use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Extension, Json,
};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_core::model::{Entity, Memory};

use crate::auth::Identity;
use crate::AppState;

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

/// Format epoch-millis as an RFC 3339 / ISO-8601 UTC timestamp, matching how
/// pydantic serializes the Python `created_at` (`DateTime(timezone=True)`).
fn rfc3339(ms: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or_else(|| chrono::DateTime::<chrono::Utc>::from_timestamp_millis(0).unwrap())
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

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

// ---- MemoryResponse (mirrors routers/memories.py MemoryResponse) ----------

/// Byte-compatible with the Python `MemoryResponse`. Fields the portable core
/// does not model (`relationships`, `collaborators`, `is_public`,
/// `processing_status`, `metadata`, `updated_at`, `task_id`) are emitted with the
/// same defaults the Postgres adapter writes, so a Rust-served response is
/// indistinguishable from a Python-served one for these strangled routes.
#[derive(Serialize)]
struct MemoryResponse {
    id: String,
    project_id: String,
    title: String,
    content: String,
    content_type: String,
    tags: Vec<String>,
    entities: Vec<Value>,
    relationships: Vec<Value>,
    version: u32,
    author_id: String,
    collaborators: Vec<String>,
    is_public: bool,
    status: String,
    processing_status: String,
    #[serde(rename = "metadata")]
    meta: Value,
    created_at: String,
    updated_at: Option<String>,
    task_id: Option<String>,
}

impl From<Memory> for MemoryResponse {
    fn from(m: Memory) -> Self {
        let entities = m
            .entities
            .into_iter()
            .map(|e| json!({ "name": e.name, "kind": e.kind }))
            .collect();
        MemoryResponse {
            id: m.id,
            project_id: m.project_id,
            title: m.title,
            content: m.content,
            content_type: m.content_type,
            tags: m.tags,
            entities,
            relationships: Vec::new(),
            version: m.version,
            author_id: m.author_id,
            collaborators: Vec::new(),
            is_public: false,
            status: m.status,
            processing_status: "COMPLETED".to_string(),
            meta: json!({}),
            created_at: rfc3339(m.created_at_ms),
            updated_at: None,
            task_id: None,
        }
    }
}

#[derive(Serialize)]
struct MemoryListResponse {
    memories: Vec<MemoryResponse>,
    total: usize,
    page: usize,
    page_size: usize,
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

#[derive(Serialize)]
struct EpisodeResponse {
    id: String,
    name: String,
    content: String,
    status: String,
    created_at: Option<String>,
    message: Option<String>,
    task_id: Option<String>,
    workflow_id: Option<String>,
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
    // the Python status code while keeping the pipeline in-process. The async
    // graph-build path is a later wave (P4).
    let memory = app
        .memory
        .ingest_episode(&project_id, &identity.user_id, &episode)
        .await
        .map_err(|e| ApiError::internal(e.to_string()))?;

    let response = EpisodeResponse {
        id: memory.id.clone(),
        name: req.name.unwrap_or_else(|| memory.title.clone()),
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

#[derive(Serialize)]
struct ShortTermRecallResponse {
    results: Vec<Value>,
    total: usize,
    window_minutes: i64,
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
    use super::*;

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
