//! P7 artifacts strangler slice.
//!
//! Rust owns `GET /api/v1/artifacts`, `GET /api/v1/artifacts/{id}`, and
//! `GET /api/v1/artifacts/categories/list`, plus exact
//! `GET|PUT /api/v1/artifacts/{id}/content`, authenticated raw content reads,
//! and `DELETE /api/v1/artifacts/{id}` soft-delete. URL refresh, upload, and
//! multipart storage writes remain Python-owned.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    body::Body,
    extract::{Path, Query, State},
    http::{header, HeaderValue, StatusCode},
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};

use agistack_adapters_postgres::{
    ArtifactListQuery as PgArtifactListQuery, ArtifactRecord, PgArtifactRepository,
};
use agistack_core::ports::ObjectStore;

use crate::auth::Identity;
use crate::AppState;

#[path = "artifact_content_v2.rs"]
mod artifact_content_v2;
use artifact_content_v2::{
    get_dev_artifact_bytes, get_dev_artifact_content, get_pg_artifact_bytes,
    get_pg_artifact_content, normalize_mime_type, save_dev_artifact_content,
    save_pg_artifact_content, ArtifactContentBytes, ArtifactContentContractV2,
    ArtifactContentSaveCommandV2, ArtifactContentSaveReceipt,
};

pub(crate) type SharedArtifacts = Arc<dyn ArtifactService>;

#[async_trait]
pub(crate) trait ArtifactService: Send + Sync {
    async fn list_artifacts(
        &self,
        query: ValidatedArtifactListQuery,
    ) -> Result<ArtifactListResponse, ArtifactApiError>;

    async fn get_artifact(
        &self,
        artifact_id: &str,
    ) -> Result<Option<ArtifactView>, ArtifactApiError>;

    async fn get_artifact_bytes(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentBytes, ArtifactApiError>;

    async fn get_artifact_content(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentContractV2, ArtifactApiError>;

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentSaveCommandV2,
    ) -> Result<ArtifactContentSaveReceipt, ArtifactApiError>;

    async fn delete_artifact(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactDeleteResponse, ArtifactApiError>;
}

pub(crate) struct PgArtifactService {
    repo: PgArtifactRepository,
    object_store: Arc<dyn ObjectStore>,
}

impl PgArtifactService {
    pub(crate) fn new(repo: PgArtifactRepository, object_store: Arc<dyn ObjectStore>) -> Self {
        Self { repo, object_store }
    }
}

#[async_trait]
impl ArtifactService for PgArtifactService {
    async fn list_artifacts(
        &self,
        query: ValidatedArtifactListQuery,
    ) -> Result<ArtifactListResponse, ArtifactApiError> {
        let rows = self
            .repo
            .list(PgArtifactListQuery {
                project_id: &query.project_id,
                category: query.category.as_deref(),
                tool_execution_id: query.tool_execution_id.as_deref(),
                limit: query.limit,
            })
            .await
            .map_err(ArtifactApiError::internal)?;
        Ok(ArtifactListResponse::from_records(rows))
    }

    async fn get_artifact(
        &self,
        artifact_id: &str,
    ) -> Result<Option<ArtifactView>, ArtifactApiError> {
        self.repo
            .get(artifact_id)
            .await
            .map_err(ArtifactApiError::internal)
            .map(|record| record.map(ArtifactView::from))
    }

    async fn get_artifact_bytes(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentBytes, ArtifactApiError> {
        get_pg_artifact_bytes(self, artifact).await
    }

    async fn get_artifact_content(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentContractV2, ArtifactApiError> {
        get_pg_artifact_content(self, artifact).await
    }

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentSaveCommandV2,
    ) -> Result<ArtifactContentSaveReceipt, ArtifactApiError> {
        save_pg_artifact_content(self, artifact, request).await
    }

    async fn delete_artifact(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactDeleteResponse, ArtifactApiError> {
        self.object_store
            .delete(&artifact.object_key)
            .await
            .map_err(ArtifactApiError::internal)?;
        self.repo
            .mark_deleted(&artifact.id)
            .await
            .map_err(ArtifactApiError::internal)?
            .ok_or_else(|| ArtifactApiError::internal("Failed to delete artifact"))?;
        Ok(ArtifactDeleteResponse::deleted(&artifact.id))
    }
}

pub(crate) struct DevArtifactService {
    artifacts: Mutex<Vec<ArtifactRecord>>,
    object_store: Arc<dyn ObjectStore>,
}

impl Default for DevArtifactService {
    fn default() -> Self {
        Self::with_object_store(
            Vec::new(),
            Arc::new(agistack_adapters_mem::InMemoryObjectStore::new()),
        )
    }
}

impl DevArtifactService {
    #[cfg(test)]
    pub(crate) fn new(artifacts: Vec<ArtifactRecord>) -> Self {
        Self::with_object_store(
            artifacts,
            Arc::new(agistack_adapters_mem::InMemoryObjectStore::new()),
        )
    }

    pub(crate) fn with_object_store(
        artifacts: Vec<ArtifactRecord>,
        object_store: Arc<dyn ObjectStore>,
    ) -> Self {
        Self {
            artifacts: Mutex::new(artifacts),
            object_store,
        }
    }
}

#[async_trait]
impl ArtifactService for DevArtifactService {
    async fn list_artifacts(
        &self,
        query: ValidatedArtifactListQuery,
    ) -> Result<ArtifactListResponse, ArtifactApiError> {
        let artifacts = self
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        let mut records = artifacts
            .iter()
            .filter(|artifact| artifact.project_id == query.project_id)
            .filter(|artifact| artifact.status == "ready")
            .filter(|artifact| {
                query
                    .category
                    .as_deref()
                    .is_none_or(|category| artifact.category == category)
            })
            .filter(|artifact| {
                query
                    .tool_execution_id
                    .as_deref()
                    .is_none_or(|tool_execution_id| {
                        artifact.tool_execution_id.as_deref() == Some(tool_execution_id)
                    })
            })
            .cloned()
            .collect::<Vec<_>>();
        records.sort_by(|left, right| {
            right
                .created_at
                .cmp(&left.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        records.truncate(query.limit as usize);
        Ok(ArtifactListResponse::from_records(records))
    }

    async fn get_artifact(
        &self,
        artifact_id: &str,
    ) -> Result<Option<ArtifactView>, ArtifactApiError> {
        let artifacts = self
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        Ok(artifacts
            .iter()
            .find(|artifact| artifact.id == artifact_id)
            .cloned()
            .map(ArtifactView::from))
    }

    async fn get_artifact_bytes(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentBytes, ArtifactApiError> {
        get_dev_artifact_bytes(self, artifact).await
    }

    async fn get_artifact_content(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactContentContractV2, ArtifactApiError> {
        get_dev_artifact_content(self, artifact).await
    }

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentSaveCommandV2,
    ) -> Result<ArtifactContentSaveReceipt, ArtifactApiError> {
        save_dev_artifact_content(self, artifact, request).await
    }

    async fn delete_artifact(
        &self,
        artifact: &ArtifactView,
    ) -> Result<ArtifactDeleteResponse, ArtifactApiError> {
        self.object_store
            .delete(&artifact.object_key)
            .await
            .map_err(ArtifactApiError::internal)?;
        let mut artifacts = self
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        let record = artifacts
            .iter_mut()
            .find(|candidate| candidate.id == artifact.id)
            .ok_or_else(|| ArtifactApiError::internal("Failed to delete artifact"))?;
        record.status = "deleted".to_string();
        record.error_message = None;
        Ok(ArtifactDeleteResponse::deleted(&artifact.id))
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/artifacts", get(list_artifacts))
        .route("/api/v1/artifacts/", get(list_artifacts))
        .route("/api/v1/artifacts/categories/list", get(list_categories))
        .route(
            "/api/v1/artifacts/:artifact_id/content",
            get(get_artifact_content).put(update_artifact_content),
        )
        .route(
            "/api/v1/artifacts/:artifact_id/content/bytes",
            get(get_artifact_content_bytes),
        )
        .route(
            "/api/v1/artifacts/:artifact_id/download",
            get(download_artifact),
        )
        .route(
            "/api/v1/artifacts/:artifact_id",
            get(get_artifact).delete(delete_artifact),
        )
}

async fn list_artifacts(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<ArtifactListQuery>,
) -> Result<Json<ArtifactListResponse>, ArtifactApiError> {
    let query = query.validated()?;
    ensure_project_access(&app, &identity, &query.project_id).await?;
    Ok(Json(app.artifacts.list_artifacts(query).await?))
}

async fn get_artifact(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
) -> Result<Json<ArtifactView>, ArtifactApiError> {
    let artifact = app
        .artifacts
        .get_artifact(&artifact_id)
        .await?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    ensure_project_access(&app, &identity, &artifact.project_id).await?;
    Ok(Json(artifact))
}

async fn update_artifact_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
    Json(request): Json<ArtifactContentSaveCommandV2>,
) -> Result<Json<ArtifactContentSaveReceipt>, ArtifactApiError> {
    let artifact = app
        .artifacts
        .get_artifact(&artifact_id)
        .await?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    ensure_project_access(&app, &identity, &artifact.project_id).await?;
    if artifact.status != "ready" {
        return Err(ArtifactApiError::bad_request(
            "Artifact cannot be updated in its current status",
        ));
    }
    Ok(Json(
        app.artifacts
            .update_artifact_content(&artifact, request)
            .await?,
    ))
}

async fn get_artifact_content(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
) -> Result<Json<ArtifactContentContractV2>, ArtifactApiError> {
    let artifact = app
        .artifacts
        .get_artifact(&artifact_id)
        .await?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    ensure_project_access(&app, &identity, &artifact.project_id).await?;
    if artifact.status != "ready" {
        return Err(ArtifactApiError::bad_request(
            "Artifact content is not ready",
        ));
    }
    Ok(Json(app.artifacts.get_artifact_content(&artifact).await?))
}

async fn get_artifact_content_bytes(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
) -> Result<Response, ArtifactApiError> {
    artifact_bytes_response(&app, &identity, &artifact_id, false).await
}

async fn download_artifact(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
) -> Result<Response, ArtifactApiError> {
    artifact_bytes_response(&app, &identity, &artifact_id, true).await
}

async fn artifact_bytes_response(
    app: &AppState,
    identity: &Identity,
    artifact_id: &str,
    attachment: bool,
) -> Result<Response, ArtifactApiError> {
    let artifact = app
        .artifacts
        .get_artifact(artifact_id)
        .await?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    ensure_project_access(app, identity, &artifact.project_id).await?;
    if artifact.status != "ready" {
        return Err(ArtifactApiError::bad_request(
            "Artifact content is not ready",
        ));
    }
    let content = app.artifacts.get_artifact_bytes(&artifact).await?;
    let content_type = HeaderValue::from_str(&normalize_mime_type(&content.mime_type))
        .map_err(|_| ArtifactApiError::internal("Artifact MIME type is invalid"))?;
    let mut builder = Response::builder()
        .status(StatusCode::OK)
        .header(header::CONTENT_TYPE, content_type)
        .header(header::CACHE_CONTROL, "private, no-store")
        .header(header::X_CONTENT_TYPE_OPTIONS, "nosniff");
    if attachment {
        builder = builder.header(header::CONTENT_DISPOSITION, "attachment");
    }
    builder
        .body(Body::from(content.bytes))
        .map_err(ArtifactApiError::internal)
}

async fn delete_artifact(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(artifact_id): Path<String>,
) -> Result<Json<ArtifactDeleteResponse>, ArtifactApiError> {
    let artifact = app
        .artifacts
        .get_artifact(&artifact_id)
        .await?
        .ok_or_else(|| ArtifactApiError::not_found("Artifact not found"))?;
    ensure_project_access(&app, &identity, &artifact.project_id).await?;
    Ok(Json(app.artifacts.delete_artifact(&artifact).await?))
}

async fn list_categories(
    Extension(_identity): Extension<Identity>,
) -> Json<ArtifactCategoriesResponse> {
    Json(artifact_categories_response())
}

async fn ensure_project_access(
    app: &AppState,
    identity: &Identity,
    project_id: &str,
) -> Result<(), ArtifactApiError> {
    let allowed = app
        .auth
        .can_access_project(&identity.user_id, project_id)
        .await
        .map_err(ArtifactApiError::internal)?;
    if allowed {
        Ok(())
    } else {
        Err(ArtifactApiError::forbidden("Access denied to project"))
    }
}

#[derive(Debug, Clone, Deserialize)]
struct ArtifactListQuery {
    project_id: String,
    category: Option<String>,
    tool_execution_id: Option<String>,
    limit: Option<i64>,
}

impl ArtifactListQuery {
    fn validated(self) -> Result<ValidatedArtifactListQuery, ArtifactApiError> {
        let limit = self.limit.unwrap_or(100);
        if !(1..=500).contains(&limit) {
            return Err(ArtifactApiError::unprocessable(
                "limit must be greater than or equal to 1 and less than or equal to 500",
            ));
        }
        let category = self
            .category
            .map(|category| validate_category(&category))
            .transpose()?;
        Ok(ValidatedArtifactListQuery {
            project_id: self.project_id,
            category,
            tool_execution_id: blank_to_none(self.tool_execution_id),
            limit,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ValidatedArtifactListQuery {
    project_id: String,
    category: Option<String>,
    tool_execution_id: Option<String>,
    limit: i64,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ArtifactView {
    id: String,
    project_id: String,
    tenant_id: String,
    sandbox_id: Option<String>,
    tool_execution_id: Option<String>,
    conversation_id: Option<String>,
    filename: String,
    mime_type: String,
    category: String,
    size_bytes: i64,
    #[serde(skip)]
    object_key: String,
    url: Option<String>,
    preview_url: Option<String>,
    status: String,
    error_message: Option<String>,
    source_tool: Option<String>,
    source_path: Option<String>,
    #[serde(rename = "metadata")]
    metadata_json: Value,
    #[serde(skip)]
    content_revision: i64,
    #[serde(skip)]
    content_hash: Option<String>,
    created_at: String,
}

impl From<ArtifactRecord> for ArtifactView {
    fn from(record: ArtifactRecord) -> Self {
        Self {
            id: record.id,
            project_id: record.project_id,
            tenant_id: record.tenant_id,
            sandbox_id: record.sandbox_id,
            tool_execution_id: record.tool_execution_id,
            conversation_id: record.conversation_id,
            filename: record.filename,
            mime_type: record.mime_type,
            category: record.category,
            size_bytes: record.size_bytes,
            object_key: record.object_key,
            url: record.url,
            preview_url: record.preview_url,
            status: record.status,
            error_message: record.error_message,
            source_tool: record.source_tool,
            source_path: record.source_path,
            metadata_json: record.metadata,
            content_revision: record.content_revision,
            content_hash: record.content_hash,
            created_at: python_iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ArtifactDeleteResponse {
    status: &'static str,
    artifact_id: String,
}

impl ArtifactDeleteResponse {
    fn deleted(artifact_id: &str) -> Self {
        Self {
            status: "deleted",
            artifact_id: artifact_id.to_string(),
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ArtifactListResponse {
    artifacts: Vec<ArtifactView>,
    total: i64,
}

impl ArtifactListResponse {
    fn from_records(records: Vec<ArtifactRecord>) -> Self {
        let artifacts = records
            .into_iter()
            .map(ArtifactView::from)
            .collect::<Vec<_>>();
        Self {
            total: artifacts.len() as i64,
            artifacts,
        }
    }
}

fn validate_category(value: &str) -> Result<String, ArtifactApiError> {
    let trimmed = value.trim();
    if ARTIFACT_CATEGORIES
        .iter()
        .any(|category| category.value == trimmed)
    {
        Ok(trimmed.to_string())
    } else {
        Err(ArtifactApiError::bad_request("Invalid artifact category"))
    }
}

#[derive(Debug, Clone, Copy)]
struct ArtifactCategorySpec {
    value: &'static str,
    label: &'static str,
    description: &'static str,
}

const ARTIFACT_CATEGORIES: &[ArtifactCategorySpec] = &[
    ArtifactCategorySpec {
        value: "image",
        label: "Image",
        description: "Images (PNG, JPEG, GIF, SVG, etc.)",
    },
    ArtifactCategorySpec {
        value: "video",
        label: "Video",
        description: "Videos (MP4, WebM, MOV, etc.)",
    },
    ArtifactCategorySpec {
        value: "audio",
        label: "Audio",
        description: "Audio files (MP3, WAV, OGG, etc.)",
    },
    ArtifactCategorySpec {
        value: "document",
        label: "Document",
        description: "Documents (PDF, TXT, HTML, Markdown)",
    },
    ArtifactCategorySpec {
        value: "code",
        label: "Code",
        description: "Source code files (Python, JavaScript, etc.)",
    },
    ArtifactCategorySpec {
        value: "data",
        label: "Data",
        description: "Data files (JSON, CSV, XML, YAML)",
    },
    ArtifactCategorySpec {
        value: "archive",
        label: "Archive",
        description: "Archives (ZIP, TAR, GZ)",
    },
    ArtifactCategorySpec {
        value: "other",
        label: "Other",
        description: "Other file types",
    },
];

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ArtifactCategoriesResponse {
    categories: Vec<ArtifactCategoryView>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct ArtifactCategoryView {
    value: &'static str,
    label: &'static str,
    description: &'static str,
}

fn artifact_categories_response() -> ArtifactCategoriesResponse {
    ArtifactCategoriesResponse {
        categories: ARTIFACT_CATEGORIES
            .iter()
            .map(|category| ArtifactCategoryView {
                value: category.value,
                label: category.label,
                description: category.description,
            })
            .collect(),
    }
}

fn blank_to_none(value: Option<String>) -> Option<String> {
    value.and_then(|raw| {
        let trimmed = raw.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

fn python_iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, false)
}

#[derive(Debug)]
pub(crate) struct ArtifactApiError {
    status: StatusCode,
    detail: String,
    reason_code: Option<String>,
    server_revision: Option<i64>,
    server_content_hash: Option<String>,
}

impl ArtifactApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
            reason_code: None,
            server_revision: None,
            server_content_hash: None,
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn unsupported_media(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNSUPPORTED_MEDIA_TYPE, detail)
    }

    fn conflict(
        detail: impl Into<String>,
        reason_code: impl Into<String>,
        server_revision: i64,
        server_content_hash: impl Into<String>,
    ) -> Self {
        Self {
            status: StatusCode::CONFLICT,
            detail: detail.into(),
            reason_code: Some(reason_code.into()),
            server_revision: Some(server_revision),
            server_content_hash: Some(server_content_hash.into()),
        }
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for ArtifactApiError {
    fn into_response(self) -> Response {
        let body = match (
            self.reason_code,
            self.server_revision,
            self.server_content_hash,
        ) {
            (Some(reason_code), Some(server_revision), Some(server_content_hash)) => json!({
                "detail": self.detail,
                "reason_code": reason_code,
                "server_revision": server_revision,
                "server_content_hash": server_content_hash,
            }),
            _ => json!({ "detail": self.detail }),
        };
        (self.status, Json(body)).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_mem::InMemoryObjectStore;
    use chrono::TimeZone;

    fn artifact(
        id: &str,
        project_id: &str,
        status: &str,
        category: &str,
        tool_execution_id: Option<&str>,
        created_at: DateTime<Utc>,
    ) -> ArtifactRecord {
        ArtifactRecord {
            id: id.to_string(),
            project_id: project_id.to_string(),
            tenant_id: "tenant-artifacts".to_string(),
            sandbox_id: Some("sandbox-1".to_string()),
            tool_execution_id: tool_execution_id.map(str::to_string),
            conversation_id: Some("conversation-1".to_string()),
            filename: format!("{id}.txt"),
            mime_type: "text/plain".to_string(),
            category: category.to_string(),
            size_bytes: 12,
            object_key: format!("artifacts/{id}.txt"),
            url: Some(format!("https://storage.example/{id}.txt")),
            preview_url: None,
            status: status.to_string(),
            error_message: None,
            source_tool: Some("terminal".to_string()),
            source_path: Some(format!("/workspace/{id}.txt")),
            metadata: json!({ "line_count": 3 }),
            content_revision: 1,
            content_hash: None,
            created_at,
        }
    }

    #[tokio::test]
    async fn dev_service_lists_ready_project_artifacts_newest_first_with_filters() {
        let older = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let newer = Utc.with_ymd_and_hms(2026, 1, 3, 3, 4, 5).unwrap();
        let service = DevArtifactService::new(vec![
            artifact(
                "artifact-old",
                "project-1",
                "ready",
                "document",
                Some("tool-1"),
                older,
            ),
            artifact(
                "artifact-new",
                "project-1",
                "ready",
                "document",
                Some("tool-1"),
                newer,
            ),
            artifact(
                "artifact-image",
                "project-1",
                "ready",
                "image",
                Some("tool-1"),
                newer,
            ),
            artifact(
                "artifact-pending",
                "project-1",
                "pending",
                "document",
                Some("tool-1"),
                newer,
            ),
            artifact(
                "artifact-other-project",
                "project-2",
                "ready",
                "document",
                Some("tool-1"),
                newer,
            ),
        ]);

        let response = service
            .list_artifacts(ValidatedArtifactListQuery {
                project_id: "project-1".to_string(),
                category: Some("document".to_string()),
                tool_execution_id: Some("tool-1".to_string()),
                limit: 10,
            })
            .await
            .expect("list artifacts");

        assert_eq!(response.total, 2);
        assert_eq!(response.artifacts[0].id, "artifact-new");
        assert_eq!(response.artifacts[1].id, "artifact-old");
    }

    #[tokio::test]
    async fn dev_service_updates_content_storage_and_python_response_shape() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let object_store = Arc::new(InMemoryObjectStore::new());
        object_store
            .put(
                "artifacts/artifact-1.txt",
                b"old text".to_vec(),
                Some("text/plain"),
            )
            .await
            .expect("seed object");
        let service = DevArtifactService::with_object_store(
            vec![artifact(
                "artifact-1",
                "project-artifacts",
                "ready",
                "document",
                Some("tool-1"),
                created_at,
            )],
            object_store.clone(),
        );
        let artifact = service
            .get_artifact("artifact-1")
            .await
            .expect("get artifact")
            .expect("artifact exists");

        let response = service
            .update_artifact_content(
                &artifact,
                ArtifactContentSaveCommandV2 {
                    contract_version: 2,
                    expected_revision: 1,
                    content_hash:
                        "sha256:87fa2bcb0c6106cb5512f75ccca21dd6ce1422ea3b00d4de8c7ebc96c48acbe3"
                            .to_string(),
                    idempotency_key: "artifact-1:save:0001".to_string(),
                    content: "updated text".to_string(),
                },
            )
            .await
            .expect("update artifact content");

        assert_eq!(
            object_store
                .get(
                    "artifacts/tenant-artifacts/project-artifacts/artifact-1/versions/\
                     r2-87fa2bcb0c6106cb5512f75ccca21dd6ce1422ea3b00d4de8c7ebc96c48acbe3",
                )
                .await
                .expect("read object"),
            Some(b"updated text".to_vec())
        );
        let value = serde_json::to_value(response).expect("serialize artifact content update");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/artifact_content_update_response.json"
        ))
        .expect("artifact content update golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn dev_service_deletes_storage_and_python_response_shape() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let object_store = Arc::new(InMemoryObjectStore::new());
        object_store
            .put(
                "artifacts/artifact-1.txt",
                b"old text".to_vec(),
                Some("text/plain"),
            )
            .await
            .expect("seed object");
        let service = DevArtifactService::with_object_store(
            vec![artifact(
                "artifact-1",
                "project-artifacts",
                "ready",
                "document",
                Some("tool-1"),
                created_at,
            )],
            object_store.clone(),
        );
        let artifact = service
            .get_artifact("artifact-1")
            .await
            .expect("get artifact")
            .expect("artifact exists");

        let response = service
            .delete_artifact(&artifact)
            .await
            .expect("delete artifact");

        assert_eq!(
            object_store
                .get("artifacts/artifact-1.txt")
                .await
                .expect("read deleted object"),
            None
        );
        let deleted = service
            .get_artifact("artifact-1")
            .await
            .expect("get deleted artifact")
            .expect("deleted artifact row remains");
        assert_eq!(deleted.status, "deleted");
        let value = serde_json::to_value(response).expect("serialize artifact delete");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/artifact_delete_response.json"
        ))
        .expect("artifact delete golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn invalid_category_matches_python_error() {
        let err = ArtifactListQuery {
            project_id: "project-1".to_string(),
            category: Some("spreadsheet".to_string()),
            tool_execution_id: None,
            limit: None,
        }
        .validated()
        .expect_err("invalid category should fail");

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "Invalid artifact category");
    }

    #[test]
    fn artifact_list_response_matches_golden() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let response = ArtifactListResponse::from_records(vec![artifact(
            "artifact-1",
            "project-artifacts",
            "ready",
            "document",
            Some("tool-1"),
            created_at,
        )]);
        let value = serde_json::to_value(response).expect("serialize artifact list");
        let golden: Value =
            serde_json::from_str(include_str!("../tests/golden/artifact_list_response.json"))
                .expect("artifact list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn artifact_detail_response_matches_golden() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let value = serde_json::to_value(ArtifactView::from(artifact(
            "artifact-1",
            "project-artifacts",
            "ready",
            "document",
            Some("tool-1"),
            created_at,
        )))
        .expect("serialize artifact detail");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/artifact_detail_response.json"
        ))
        .expect("artifact detail golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn artifact_categories_response_matches_golden() {
        let value =
            serde_json::to_value(artifact_categories_response()).expect("serialize categories");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/artifact_categories_response.json"
        ))
        .expect("artifact categories golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn dev_service_reads_authenticated_content_contract_and_raw_bytes() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let object_store = Arc::new(InMemoryObjectStore::new());
        object_store
            .put(
                "artifacts/artifact-v2.txt",
                b"seed".to_vec(),
                Some("text/plain"),
            )
            .await
            .expect("seed object");
        let service = DevArtifactService::with_object_store(
            vec![artifact(
                "artifact-v2",
                "project-artifacts",
                "ready",
                "document",
                Some("tool-1"),
                created_at,
            )],
            object_store,
        );
        let artifact = service
            .get_artifact("artifact-v2")
            .await
            .expect("get artifact")
            .expect("artifact exists");

        let content = service
            .get_artifact_content(&artifact)
            .await
            .expect("get text authority");
        let raw = service
            .get_artifact_bytes(&artifact)
            .await
            .expect("get raw bytes");

        assert_eq!(content.contract_version, 2);
        assert_eq!(content.artifact_id, "artifact-v2");
        assert_eq!(content.revision, 1);
        assert_eq!(
            content.content_hash,
            "sha256:19b25856e1c150ca834cffc8b59b23adbd0ec0389e58eb22b3b64768098d002b"
        );
        assert_eq!(content.mime_type, "text/plain");
        assert_eq!(content.content, "seed");
        assert_eq!(raw.bytes, b"seed");
        assert_eq!(raw.mime_type, "text/plain");
    }

    #[tokio::test]
    async fn dev_service_versions_content_and_enforces_revision_and_idempotency() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let object_store = Arc::new(InMemoryObjectStore::new());
        object_store
            .put(
                "artifacts/artifact-v2.txt",
                b"seed".to_vec(),
                Some("text/plain"),
            )
            .await
            .expect("seed object");
        let service = DevArtifactService::with_object_store(
            vec![artifact(
                "artifact-v2",
                "project-artifacts",
                "ready",
                "document",
                Some("tool-1"),
                created_at,
            )],
            object_store.clone(),
        );
        let artifact = service
            .get_artifact("artifact-v2")
            .await
            .expect("get artifact")
            .expect("artifact exists");
        let command = ArtifactContentSaveCommandV2 {
            contract_version: 2,
            expected_revision: 1,
            content_hash: "sha256:27eb5e51506c911f6fc4bb345c0d9db6f60415fceab7c18e1e9b862637415777"
                .to_string(),
            idempotency_key: "artifact-v2:save:0001".to_string(),
            content: "updated".to_string(),
        };

        let first = service
            .update_artifact_content(&artifact, command.clone())
            .await
            .expect("first save");
        let replay = service
            .update_artifact_content(&artifact, command.clone())
            .await
            .expect("idempotent replay");

        assert_eq!(first.revision, 2);
        assert_eq!(first.content_hash, command.content_hash);
        assert!(!first.duplicate);
        assert_eq!(replay.revision, 2);
        assert!(replay.duplicate);
        let version_key = format!(
            "artifacts/tenant-artifacts/project-artifacts/artifact-v2/versions/r2-{}",
            command.content_hash.trim_start_matches("sha256:")
        );
        assert_eq!(
            object_store.get(&version_key).await.expect("read version"),
            Some(b"updated".to_vec())
        );
        assert_eq!(
            object_store
                .get("artifacts/artifact-v2.txt")
                .await
                .expect("read original"),
            Some(b"seed".to_vec())
        );

        let key_conflict = service
            .update_artifact_content(
                &artifact,
                ArtifactContentSaveCommandV2 {
                    contract_version: 2,
                    expected_revision: 1,
                    content_hash:
                        "sha256:9d6f965ac832e40a5df6c06afe983e3b449c07b843ff51ce76204de05c690d11"
                            .to_string(),
                    idempotency_key: command.idempotency_key,
                    content: "different".to_string(),
                },
            )
            .await
            .expect_err("same key with a different payload must fail");
        assert_eq!(key_conflict.status, StatusCode::CONFLICT);
        assert_eq!(
            key_conflict.reason_code.as_deref(),
            Some("artifact_content_idempotency_conflict")
        );
        assert_eq!(key_conflict.server_revision, Some(2));
        assert_eq!(
            key_conflict.server_content_hash.as_deref(),
            Some(first.content_hash.as_str())
        );

        let revision_conflict = service
            .update_artifact_content(
                &artifact,
                ArtifactContentSaveCommandV2 {
                    contract_version: 2,
                    expected_revision: 1,
                    content_hash:
                        "sha256:804f51f71254c4081e37e7c887073560f4a6fa6cdad202e9ac67e032c43ed1e1"
                            .to_string(),
                    idempotency_key: "artifact-v2:save:0002".to_string(),
                    content: "newer".to_string(),
                },
            )
            .await
            .expect_err("stale revision must fail");
        assert_eq!(revision_conflict.status, StatusCode::CONFLICT);
        assert_eq!(
            revision_conflict.reason_code.as_deref(),
            Some("artifact_content_revision_conflict")
        );
        assert_eq!(revision_conflict.server_revision, Some(2));
    }
}
