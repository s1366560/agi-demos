//! P7 artifacts strangler slice.
//!
//! Rust owns `GET /api/v1/artifacts`, `GET /api/v1/artifacts/{id}`, and
//! `GET /api/v1/artifacts/categories/list`, plus exact
//! `PUT /api/v1/artifacts/{id}/content` content save-back and
//! `DELETE /api/v1/artifacts/{id}` soft-delete. Download, URL refresh, upload,
//! and multipart storage writes remain Python-owned.

use std::sync::{Arc, Mutex};

use async_trait::async_trait;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, put},
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

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentUpdateRequest,
    ) -> Result<ArtifactContentUpdateResponse, ArtifactApiError>;

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

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentUpdateRequest,
    ) -> Result<ArtifactContentUpdateResponse, ArtifactApiError> {
        let bytes = request.content.into_bytes();
        let size_bytes = i64::try_from(bytes.len())
            .map_err(|_| ArtifactApiError::bad_request("Artifact content is too large"))?;
        self.object_store
            .put(&artifact.object_key, bytes, Some(&artifact.mime_type))
            .await
            .map_err(ArtifactApiError::internal)?;
        let updated = self
            .repo
            .update_content_metadata(&artifact.id, size_bytes)
            .await
            .map_err(ArtifactApiError::internal)?
            .ok_or_else(|| ArtifactApiError::internal("Failed to update artifact content"))?;
        Ok(ArtifactContentUpdateResponse::from(updated))
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

    async fn update_artifact_content(
        &self,
        artifact: &ArtifactView,
        request: ArtifactContentUpdateRequest,
    ) -> Result<ArtifactContentUpdateResponse, ArtifactApiError> {
        let bytes = request.content.into_bytes();
        let size_bytes = i64::try_from(bytes.len())
            .map_err(|_| ArtifactApiError::bad_request("Artifact content is too large"))?;
        self.object_store
            .put(&artifact.object_key, bytes, Some(&artifact.mime_type))
            .await
            .map_err(ArtifactApiError::internal)?;
        let mut artifacts = self
            .artifacts
            .lock()
            .map_err(|_| ArtifactApiError::internal("poisoned artifact lock"))?;
        let record = artifacts
            .iter_mut()
            .find(|candidate| candidate.id == artifact.id && candidate.status == "ready")
            .ok_or_else(|| ArtifactApiError::internal("Failed to update artifact content"))?;
        record.size_bytes = size_bytes;
        record.error_message = None;
        Ok(ArtifactContentUpdateResponse::from(record.clone()))
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
            put(update_artifact_content),
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
    Json(request): Json<ArtifactContentUpdateRequest>,
) -> Result<Json<ArtifactContentUpdateResponse>, ArtifactApiError> {
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
            created_at: python_iso8601(record.created_at),
        }
    }
}

#[derive(Debug, Clone, Deserialize, PartialEq, Eq)]
pub(crate) struct ArtifactContentUpdateRequest {
    content: String,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct ArtifactContentUpdateResponse {
    artifact_id: String,
    size_bytes: i64,
    url: Option<String>,
}

impl From<ArtifactRecord> for ArtifactContentUpdateResponse {
    fn from(record: ArtifactRecord) -> Self {
        Self {
            artifact_id: record.id,
            size_bytes: record.size_bytes,
            url: record.url,
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
}

impl ArtifactApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
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

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for ArtifactApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
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
                ArtifactContentUpdateRequest {
                    content: "updated text".to_string(),
                },
            )
            .await
            .expect("update artifact content");

        assert_eq!(
            object_store
                .get("artifacts/artifact-1.txt")
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
}
