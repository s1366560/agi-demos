//! P7 attachments strangler slice.
//!
//! Rust owns only `GET /api/v1/attachments` and
//! `GET /api/v1/attachments/{id}` plus exact simple upload and hard-delete.
//! Multipart initiation, part upload, completion, abort, and download URL
//! generation remain Python-owned.

use std::{
    collections::HashMap,
    sync::{Arc, Mutex},
};

use async_trait::async_trait;
use axum::{
    extract::{Multipart, Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    routing::{get, post},
    Extension, Json, Router,
};
use chrono::{DateTime, SecondsFormat, Utc};
use serde::{Deserialize, Serialize};
use serde_json::json;
use uuid::Uuid;

use agistack_adapters_postgres::{
    AttachmentListQuery as PgAttachmentListQuery, AttachmentRecord, AttachmentUploadRecord,
    PgAttachmentRepository,
};
use agistack_core::ports::ObjectStore;

use crate::auth::Identity;
use crate::AppState;

pub(crate) type SharedAttachments = Arc<dyn AttachmentService>;

#[async_trait]
pub(crate) trait AttachmentService: Send + Sync {
    async fn list_attachments(
        &self,
        user_id: &str,
        query: ValidatedAttachmentListQuery,
    ) -> Result<AttachmentListResponse, AttachmentApiError>;

    async fn get_attachment(
        &self,
        user_id: &str,
        attachment_id: &str,
    ) -> Result<Option<AttachmentView>, AttachmentApiError>;

    async fn delete_attachment(
        &self,
        attachment: &AttachmentView,
    ) -> Result<AttachmentDeleteResponse, AttachmentApiError>;

    async fn upload_simple(
        &self,
        user_id: &str,
        upload: AttachmentSimpleUpload,
    ) -> Result<AttachmentView, AttachmentApiError>;
}

pub(crate) struct PgAttachmentService {
    repo: PgAttachmentRepository,
    object_store: Arc<dyn ObjectStore>,
}

impl PgAttachmentService {
    pub(crate) fn new(repo: PgAttachmentRepository, object_store: Arc<dyn ObjectStore>) -> Self {
        Self { repo, object_store }
    }
}

#[async_trait]
impl AttachmentService for PgAttachmentService {
    async fn list_attachments(
        &self,
        user_id: &str,
        query: ValidatedAttachmentListQuery,
    ) -> Result<AttachmentListResponse, AttachmentApiError> {
        let rows = self
            .repo
            .list_visible(PgAttachmentListQuery {
                user_id,
                conversation_id: &query.conversation_id,
                status: query.status.as_deref(),
            })
            .await
            .map_err(AttachmentApiError::internal)?;
        Ok(AttachmentListResponse::from_records(rows))
    }

    async fn get_attachment(
        &self,
        user_id: &str,
        attachment_id: &str,
    ) -> Result<Option<AttachmentView>, AttachmentApiError> {
        let Some(record) = self
            .repo
            .get(attachment_id)
            .await
            .map_err(AttachmentApiError::internal)?
        else {
            return Ok(None);
        };

        let Some(project_tenant_id) = self
            .repo
            .accessible_project_tenant(user_id, &record.project_id)
            .await
            .map_err(AttachmentApiError::internal)?
        else {
            return Err(AttachmentApiError::forbidden("Access denied to project"));
        };

        if record.tenant_id != project_tenant_id {
            return Err(AttachmentApiError::forbidden("Access denied to attachment"));
        }

        Ok(Some(AttachmentView::from(record)))
    }

    async fn delete_attachment(
        &self,
        attachment: &AttachmentView,
    ) -> Result<AttachmentDeleteResponse, AttachmentApiError> {
        let _ = self.object_store.delete(&attachment.object_key).await;
        let deleted = self
            .repo
            .delete(&attachment.id)
            .await
            .map_err(AttachmentApiError::internal)?;
        if !deleted {
            return Err(AttachmentApiError::not_found("Attachment not found"));
        }
        Ok(AttachmentDeleteResponse::deleted())
    }

    async fn upload_simple(
        &self,
        user_id: &str,
        upload: AttachmentSimpleUpload,
    ) -> Result<AttachmentView, AttachmentApiError> {
        let Some(tenant_id) = self
            .repo
            .accessible_project_tenant(user_id, &upload.project_id)
            .await
            .map_err(AttachmentApiError::internal)?
        else {
            return Err(AttachmentApiError::forbidden("Access denied to project"));
        };
        let record = uploaded_record(tenant_id, upload)?;
        self.object_store
            .put(
                &record.object_key,
                record.bytes.clone(),
                Some(&record.mime_type),
            )
            .await
            .map_err(AttachmentApiError::internal)?;
        self.repo
            .insert_uploaded(record.into_pg_record())
            .await
            .map_err(AttachmentApiError::internal)
            .map(AttachmentView::from)
    }
}

pub(crate) struct DevAttachmentService {
    attachments: Mutex<Vec<AttachmentRecord>>,
    project_tenants: HashMap<String, String>,
    object_store: Arc<dyn ObjectStore>,
}

impl Default for DevAttachmentService {
    fn default() -> Self {
        Self::with_object_store(
            Vec::new(),
            HashMap::new(),
            Arc::new(agistack_adapters_mem::InMemoryObjectStore::new()),
        )
    }
}

impl DevAttachmentService {
    #[cfg(test)]
    pub(crate) fn new(
        attachments: Vec<AttachmentRecord>,
        project_tenants: HashMap<String, String>,
    ) -> Self {
        Self::with_object_store(
            attachments,
            project_tenants,
            Arc::new(agistack_adapters_mem::InMemoryObjectStore::new()),
        )
    }

    pub(crate) fn with_object_store(
        attachments: Vec<AttachmentRecord>,
        project_tenants: HashMap<String, String>,
        object_store: Arc<dyn ObjectStore>,
    ) -> Self {
        Self {
            attachments: Mutex::new(attachments),
            project_tenants,
            object_store,
        }
    }

    fn visible(&self, attachment: &AttachmentRecord) -> Result<bool, AttachmentApiError> {
        if self.project_tenants.is_empty() {
            return Ok(true);
        }
        let Some(project_tenant_id) = self.project_tenants.get(&attachment.project_id) else {
            return Ok(false);
        };
        Ok(project_tenant_id == &attachment.tenant_id)
    }
}

#[async_trait]
impl AttachmentService for DevAttachmentService {
    async fn list_attachments(
        &self,
        _user_id: &str,
        query: ValidatedAttachmentListQuery,
    ) -> Result<AttachmentListResponse, AttachmentApiError> {
        let attachments = self
            .attachments
            .lock()
            .map_err(|_| AttachmentApiError::internal("poisoned attachment lock"))?;
        let mut records = attachments
            .iter()
            .filter(|attachment| attachment.conversation_id == query.conversation_id)
            .filter(|attachment| {
                query
                    .status
                    .as_deref()
                    .is_none_or(|status| attachment.status == status)
            })
            .filter(|attachment| self.visible(attachment).unwrap_or(false))
            .cloned()
            .collect::<Vec<_>>();
        records.sort_by(|left, right| {
            left.created_at
                .cmp(&right.created_at)
                .then_with(|| left.id.cmp(&right.id))
        });
        Ok(AttachmentListResponse::from_records(records))
    }

    async fn get_attachment(
        &self,
        _user_id: &str,
        attachment_id: &str,
    ) -> Result<Option<AttachmentView>, AttachmentApiError> {
        let attachments = self
            .attachments
            .lock()
            .map_err(|_| AttachmentApiError::internal("poisoned attachment lock"))?;
        let Some(record) = attachments
            .iter()
            .find(|attachment| attachment.id == attachment_id)
            .cloned()
        else {
            return Ok(None);
        };

        if !self.project_tenants.is_empty() {
            let Some(project_tenant_id) = self.project_tenants.get(&record.project_id) else {
                return Err(AttachmentApiError::forbidden("Access denied to project"));
            };
            if project_tenant_id != &record.tenant_id {
                return Err(AttachmentApiError::forbidden("Access denied to attachment"));
            }
        }

        Ok(Some(AttachmentView::from(record)))
    }

    async fn delete_attachment(
        &self,
        attachment: &AttachmentView,
    ) -> Result<AttachmentDeleteResponse, AttachmentApiError> {
        let _ = self.object_store.delete(&attachment.object_key).await;
        let mut attachments = self
            .attachments
            .lock()
            .map_err(|_| AttachmentApiError::internal("poisoned attachment lock"))?;
        let Some(index) = attachments
            .iter()
            .position(|candidate| candidate.id == attachment.id)
        else {
            return Err(AttachmentApiError::not_found("Attachment not found"));
        };
        attachments.remove(index);
        Ok(AttachmentDeleteResponse::deleted())
    }

    async fn upload_simple(
        &self,
        _user_id: &str,
        upload: AttachmentSimpleUpload,
    ) -> Result<AttachmentView, AttachmentApiError> {
        let tenant_id = if self.project_tenants.is_empty() {
            "tenant-dev".to_string()
        } else {
            self.project_tenants
                .get(&upload.project_id)
                .cloned()
                .ok_or_else(|| AttachmentApiError::forbidden("Access denied to project"))?
        };
        let record = uploaded_record(tenant_id, upload)?;
        self.object_store
            .put(
                &record.object_key,
                record.bytes.clone(),
                Some(&record.mime_type),
            )
            .await
            .map_err(AttachmentApiError::internal)?;
        let view = AttachmentView::from(record.as_attachment_record());
        let mut attachments = self
            .attachments
            .lock()
            .map_err(|_| AttachmentApiError::internal("poisoned attachment lock"))?;
        attachments.push(record.as_attachment_record());
        Ok(view)
    }
}

pub(crate) fn router() -> Router<AppState> {
    Router::new()
        .route("/api/v1/attachments", get(list_attachments))
        .route("/api/v1/attachments/", get(list_attachments))
        .route("/api/v1/attachments/upload/simple", post(upload_simple))
        .route(
            "/api/v1/attachments/:attachment_id",
            get(get_attachment).delete(delete_attachment),
        )
}

async fn list_attachments(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Query(query): Query<AttachmentListQuery>,
) -> Result<Json<AttachmentListResponse>, AttachmentApiError> {
    let query = query.validated()?;
    Ok(Json(
        app.attachments
            .list_attachments(&identity.user_id, query)
            .await?,
    ))
}

async fn get_attachment(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(attachment_id): Path<String>,
) -> Result<Json<AttachmentView>, AttachmentApiError> {
    let attachment = app
        .attachments
        .get_attachment(&identity.user_id, &attachment_id)
        .await?
        .ok_or_else(|| AttachmentApiError::not_found("Attachment not found"))?;
    Ok(Json(attachment))
}

async fn delete_attachment(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    Path(attachment_id): Path<String>,
) -> Result<Json<AttachmentDeleteResponse>, AttachmentApiError> {
    let attachment = app
        .attachments
        .get_attachment(&identity.user_id, &attachment_id)
        .await?
        .ok_or_else(|| AttachmentApiError::not_found("Attachment not found"))?;
    Ok(Json(app.attachments.delete_attachment(&attachment).await?))
}

async fn upload_simple(
    State(app): State<AppState>,
    Extension(identity): Extension<Identity>,
    multipart: Multipart,
) -> Result<Json<AttachmentView>, AttachmentApiError> {
    let upload = parse_simple_upload(multipart).await?;
    Ok(Json(
        app.attachments
            .upload_simple(&identity.user_id, upload)
            .await?,
    ))
}

#[derive(Debug, Clone, Deserialize)]
struct AttachmentListQuery {
    conversation_id: String,
    status: Option<String>,
}

impl AttachmentListQuery {
    fn validated(self) -> Result<ValidatedAttachmentListQuery, AttachmentApiError> {
        let status = self
            .status
            .map(|status| validate_status(&status))
            .transpose()?
            .flatten();
        Ok(ValidatedAttachmentListQuery {
            conversation_id: self.conversation_id,
            status,
        })
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct ValidatedAttachmentListQuery {
    conversation_id: String,
    status: Option<String>,
}

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct AttachmentView {
    id: String,
    conversation_id: String,
    project_id: String,
    filename: String,
    mime_type: String,
    size_bytes: i64,
    #[serde(skip)]
    object_key: String,
    purpose: String,
    status: String,
    sandbox_path: Option<String>,
    created_at: String,
    error_message: Option<String>,
}

impl From<AttachmentRecord> for AttachmentView {
    fn from(record: AttachmentRecord) -> Self {
        Self {
            id: record.id,
            conversation_id: record.conversation_id,
            project_id: record.project_id,
            filename: record.filename,
            mime_type: record.mime_type,
            size_bytes: record.size_bytes,
            object_key: record.object_key,
            purpose: record.purpose,
            status: record.status,
            sandbox_path: record.sandbox_path,
            created_at: python_iso8601(record.created_at),
            error_message: record.error_message,
        }
    }
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub(crate) struct AttachmentDeleteResponse {
    success: bool,
    message: &'static str,
}

impl AttachmentDeleteResponse {
    fn deleted() -> Self {
        Self {
            success: true,
            message: "Attachment deleted",
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub(crate) struct AttachmentSimpleUpload {
    conversation_id: String,
    project_id: String,
    purpose: String,
    filename: String,
    mime_type: String,
    bytes: Vec<u8>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct UploadedAttachmentRecord {
    id: String,
    conversation_id: String,
    project_id: String,
    tenant_id: String,
    filename: String,
    mime_type: String,
    size_bytes: i64,
    object_key: String,
    purpose: String,
    created_at: DateTime<Utc>,
    bytes: Vec<u8>,
}

impl UploadedAttachmentRecord {
    fn as_attachment_record(&self) -> AttachmentRecord {
        AttachmentRecord {
            id: self.id.clone(),
            conversation_id: self.conversation_id.clone(),
            project_id: self.project_id.clone(),
            tenant_id: self.tenant_id.clone(),
            filename: self.filename.clone(),
            mime_type: self.mime_type.clone(),
            size_bytes: self.size_bytes,
            object_key: self.object_key.clone(),
            purpose: self.purpose.clone(),
            status: "uploaded".to_string(),
            sandbox_path: None,
            created_at: self.created_at,
            error_message: None,
        }
    }

    fn into_pg_record(self) -> AttachmentUploadRecord {
        AttachmentUploadRecord {
            id: self.id,
            conversation_id: self.conversation_id,
            project_id: self.project_id,
            tenant_id: self.tenant_id,
            filename: self.filename,
            mime_type: self.mime_type,
            size_bytes: self.size_bytes,
            object_key: self.object_key,
            purpose: self.purpose,
            created_at: self.created_at,
        }
    }
}

async fn parse_simple_upload(
    mut multipart: Multipart,
) -> Result<AttachmentSimpleUpload, AttachmentApiError> {
    let mut conversation_id = None;
    let mut project_id = None;
    let mut purpose = None;
    let mut file = None;

    while let Some(field) = multipart
        .next_field()
        .await
        .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?
    {
        let Some(name) = field.name().map(str::to_string) else {
            continue;
        };
        match name.as_str() {
            "conversation_id" => {
                conversation_id = Some(
                    field
                        .text()
                        .await
                        .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?,
                );
            }
            "project_id" => {
                project_id = Some(
                    field
                        .text()
                        .await
                        .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?,
                );
            }
            "purpose" => {
                purpose = Some(
                    field
                        .text()
                        .await
                        .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?,
                );
            }
            "file" => {
                let filename = field.file_name().unwrap_or("unnamed").to_string();
                let filename = if filename.is_empty() {
                    "unnamed".to_string()
                } else {
                    filename
                };
                let mime_type = field
                    .content_type()
                    .unwrap_or("application/octet-stream")
                    .to_string();
                let bytes = field
                    .bytes()
                    .await
                    .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?
                    .to_vec();
                file = Some((filename, mime_type, bytes));
            }
            _ => {}
        }
    }

    let (filename, mime_type, bytes) =
        file.ok_or_else(|| AttachmentApiError::unprocessable("Missing form field: file"))?;
    Ok(AttachmentSimpleUpload {
        conversation_id: required_form_field(conversation_id, "conversation_id")?,
        project_id: required_form_field(project_id, "project_id")?,
        purpose: purpose.unwrap_or_else(|| "both".to_string()),
        filename,
        mime_type,
        bytes,
    })
}

fn required_form_field(value: Option<String>, field: &str) -> Result<String, AttachmentApiError> {
    let Some(value) = value else {
        return Err(AttachmentApiError::unprocessable(format!(
            "Missing form field: {field}"
        )));
    };
    if value.is_empty() {
        return Err(AttachmentApiError::unprocessable(format!(
            "Missing form field: {field}"
        )));
    }
    Ok(value)
}

fn uploaded_record(
    tenant_id: String,
    upload: AttachmentSimpleUpload,
) -> Result<UploadedAttachmentRecord, AttachmentApiError> {
    let purpose = validate_purpose(&upload.purpose)?;
    validate_upload_file(
        &upload.filename,
        &upload.mime_type,
        upload.bytes.len(),
        purpose,
    )?;
    let id = Uuid::new_v4().simple().to_string();
    let created_at = Utc::now();
    let size_bytes = i64::try_from(upload.bytes.len())
        .map_err(|_| AttachmentApiError::bad_request("Invalid upload request"))?;
    let object_key = attachment_object_key(
        &tenant_id,
        &upload.project_id,
        &upload.conversation_id,
        &upload.filename,
        created_at,
    );
    Ok(UploadedAttachmentRecord {
        id,
        conversation_id: upload.conversation_id,
        project_id: upload.project_id,
        tenant_id,
        filename: upload.filename,
        mime_type: upload.mime_type,
        size_bytes,
        object_key,
        purpose: purpose.to_string(),
        created_at,
        bytes: upload.bytes,
    })
}

fn validate_purpose(raw: &str) -> Result<&'static str, AttachmentApiError> {
    match raw {
        "llm_context" => Ok("llm_context"),
        "sandbox_input" => Ok("sandbox_input"),
        "both" => Ok("both"),
        _ => Err(AttachmentApiError::bad_request(
            "Invalid attachment purpose",
        )),
    }
}

fn validate_upload_file(
    _filename: &str,
    mime_type: &str,
    size_bytes: usize,
    purpose: &str,
) -> Result<(), AttachmentApiError> {
    if size_bytes > max_upload_size_bytes(purpose) || !mime_type_allowed(mime_type, purpose) {
        return Err(AttachmentApiError::bad_request("Invalid upload request"));
    }
    Ok(())
}

fn max_upload_size_bytes(purpose: &str) -> usize {
    let llm = env_upload_max_mb("UPLOAD_MAX_SIZE_LLM_MB");
    let sandbox = env_upload_max_mb("UPLOAD_MAX_SIZE_SANDBOX_MB");
    let mb = match purpose {
        "sandbox_input" => sandbox,
        "llm_context" => llm,
        "both" => llm.min(sandbox),
        _ => llm.min(sandbox),
    };
    mb.saturating_mul(1024 * 1024)
}

fn env_upload_max_mb(name: &str) -> usize {
    std::env::var(name)
        .ok()
        .and_then(|value| value.parse::<usize>().ok())
        .filter(|value| *value > 0)
        .unwrap_or(100)
}

fn mime_type_allowed(mime_type: &str, purpose: &str) -> bool {
    if purpose == "sandbox_input" {
        return true;
    }
    LLM_ATTACHMENT_MIME_TYPES
        .iter()
        .any(|allowed| mime_matches(mime_type, allowed))
}

fn mime_matches(mime_type: &str, allowed: &str) -> bool {
    if allowed == "*/*" {
        return true;
    }
    if let Some(prefix) = allowed.strip_suffix("/*") {
        return mime_type.starts_with(prefix);
    }
    mime_type == allowed
}

fn attachment_object_key(
    tenant_id: &str,
    project_id: &str,
    conversation_id: &str,
    filename: &str,
    created_at: DateTime<Utc>,
) -> String {
    let unique = Uuid::new_v4().simple().to_string();
    let date = created_at.format("%Y%m%d");
    let unique = &unique[..12];
    match attachment_extension(filename) {
        Some(ext) => {
            format!("attachments/{tenant_id}/{project_id}/{conversation_id}/{date}_{unique}.{ext}")
        }
        None => format!("attachments/{tenant_id}/{project_id}/{conversation_id}/{date}_{unique}"),
    }
}

fn attachment_extension(filename: &str) -> Option<String> {
    filename
        .rsplit_once('.')
        .and_then(|(_, ext)| (!ext.is_empty()).then(|| ext.to_ascii_lowercase()))
}

const LLM_ATTACHMENT_MIME_TYPES: &[&str] = &[
    "image/*",
    "video/*",
    "audio/*",
    "application/pdf",
    "text/*",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.ms-excel",
    "application/msword",
    "application/vnd.ms-powerpoint",
    "application/vnd.oasis.opendocument.spreadsheet",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.presentation",
    "text/csv",
    "application/csv",
];

#[derive(Debug, Clone, Serialize, PartialEq)]
pub(crate) struct AttachmentListResponse {
    attachments: Vec<AttachmentView>,
    total: i64,
}

impl AttachmentListResponse {
    fn from_records(records: Vec<AttachmentRecord>) -> Self {
        let attachments = records
            .into_iter()
            .map(AttachmentView::from)
            .collect::<Vec<_>>();
        Self {
            total: attachments.len() as i64,
            attachments,
        }
    }
}

fn validate_status(value: &str) -> Result<Option<String>, AttachmentApiError> {
    let trimmed = value.trim();
    if trimmed.is_empty() {
        return Ok(None);
    }
    if matches!(
        trimmed,
        "pending" | "uploaded" | "processing" | "ready" | "failed" | "expired"
    ) {
        Ok(Some(trimmed.to_string()))
    } else {
        Err(AttachmentApiError::bad_request("Invalid attachment status"))
    }
}

fn python_iso8601(value: DateTime<Utc>) -> String {
    value.to_rfc3339_opts(SecondsFormat::AutoSi, false)
}

#[derive(Debug)]
pub(crate) struct AttachmentApiError {
    status: StatusCode,
    detail: String,
}

impl AttachmentApiError {
    fn new(status: StatusCode, detail: impl Into<String>) -> Self {
        Self {
            status,
            detail: detail.into(),
        }
    }

    fn bad_request(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::BAD_REQUEST, detail)
    }

    fn unprocessable(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::UNPROCESSABLE_ENTITY, detail)
    }

    fn forbidden(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::FORBIDDEN, detail)
    }

    fn not_found(detail: impl Into<String>) -> Self {
        Self::new(StatusCode::NOT_FOUND, detail)
    }

    fn internal(detail: impl std::fmt::Display) -> Self {
        Self::new(StatusCode::INTERNAL_SERVER_ERROR, detail.to_string())
    }
}

impl IntoResponse for AttachmentApiError {
    fn into_response(self) -> Response {
        (self.status, Json(json!({ "detail": self.detail }))).into_response()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use agistack_adapters_mem::InMemoryObjectStore;
    use chrono::TimeZone;
    use serde_json::Value;

    fn attachment(
        id: &str,
        conversation_id: &str,
        project_id: &str,
        tenant_id: &str,
        status: &str,
        created_at: DateTime<Utc>,
    ) -> AttachmentRecord {
        AttachmentRecord {
            id: id.to_string(),
            conversation_id: conversation_id.to_string(),
            project_id: project_id.to_string(),
            tenant_id: tenant_id.to_string(),
            filename: format!("{id}.txt"),
            mime_type: "text/plain".to_string(),
            size_bytes: 42,
            object_key: format!("attachments/{id}.txt"),
            purpose: "both".to_string(),
            status: status.to_string(),
            sandbox_path: Some(format!("/workspace/{id}.txt")),
            created_at,
            error_message: None,
        }
    }

    fn project_tenants() -> HashMap<String, String> {
        HashMap::from([("project-attachments".to_string(), "tenant-a".to_string())])
    }

    #[tokio::test]
    async fn dev_service_lists_visible_conversation_attachments_oldest_first() {
        let older = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let newer = Utc.with_ymd_and_hms(2026, 1, 3, 3, 4, 5).unwrap();
        let service = DevAttachmentService::new(
            vec![
                attachment(
                    "attachment-new",
                    "conversation-1",
                    "project-attachments",
                    "tenant-a",
                    "ready",
                    newer,
                ),
                attachment(
                    "attachment-old",
                    "conversation-1",
                    "project-attachments",
                    "tenant-a",
                    "ready",
                    older,
                ),
                attachment(
                    "attachment-pending",
                    "conversation-1",
                    "project-attachments",
                    "tenant-a",
                    "pending",
                    newer,
                ),
                attachment(
                    "attachment-other-conversation",
                    "conversation-2",
                    "project-attachments",
                    "tenant-a",
                    "ready",
                    newer,
                ),
                attachment(
                    "attachment-tenant-mismatch",
                    "conversation-1",
                    "project-attachments",
                    "tenant-b",
                    "ready",
                    newer,
                ),
            ],
            project_tenants(),
        );

        let response = service
            .list_attachments(
                "user-1",
                ValidatedAttachmentListQuery {
                    conversation_id: "conversation-1".to_string(),
                    status: Some("ready".to_string()),
                },
            )
            .await
            .expect("list attachments");

        assert_eq!(response.total, 2);
        assert_eq!(response.attachments[0].id, "attachment-old");
        assert_eq!(response.attachments[1].id, "attachment-new");
    }

    #[test]
    fn invalid_status_matches_python_error() {
        let err = AttachmentListQuery {
            conversation_id: "conversation-1".to_string(),
            status: Some("deleted".to_string()),
        }
        .validated()
        .expect_err("invalid status should fail");

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "Invalid attachment status");
    }

    #[test]
    fn attachment_list_response_matches_golden() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let response = AttachmentListResponse::from_records(vec![attachment(
            "attachment-1",
            "conversation-attachments",
            "project-attachments",
            "tenant-a",
            "ready",
            created_at,
        )]);
        let value = serde_json::to_value(response).expect("serialize attachment list");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/attachment_list_response.json"
        ))
        .expect("attachment list golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn attachment_detail_response_matches_golden() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let value = serde_json::to_value(AttachmentView::from(attachment(
            "attachment-1",
            "conversation-attachments",
            "project-attachments",
            "tenant-a",
            "ready",
            created_at,
        )))
        .expect("serialize attachment detail");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/attachment_detail_response.json"
        ))
        .expect("attachment detail golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn attachment_delete_response_matches_golden() {
        let value =
            serde_json::to_value(AttachmentDeleteResponse::deleted()).expect("serialize delete");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/attachment_delete_response.json"
        ))
        .expect("attachment delete golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[test]
    fn attachment_upload_simple_response_matches_golden() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let mut record = attachment(
            "attachment-1",
            "conversation-attachments",
            "project-attachments",
            "tenant-a",
            "uploaded",
            created_at,
        );
        record.sandbox_path = None;
        let value = serde_json::to_value(AttachmentView::from(record))
            .expect("serialize attachment upload response");
        let golden: Value = serde_json::from_str(include_str!(
            "../tests/golden/attachment_upload_simple_response.json"
        ))
        .expect("attachment upload golden must be valid JSON");
        agistack_parity::assert_parity(&golden, &value);
    }

    #[tokio::test]
    async fn dev_service_deletes_storage_record_and_python_response_shape() {
        let created_at = Utc.with_ymd_and_hms(2026, 1, 2, 3, 4, 5).unwrap();
        let object_store = Arc::new(InMemoryObjectStore::new());
        object_store
            .put(
                "attachments/attachment-1.txt",
                b"secret".to_vec(),
                Some("text/plain"),
            )
            .await
            .expect("seed object");
        let service = DevAttachmentService::with_object_store(
            vec![attachment(
                "attachment-1",
                "conversation-attachments",
                "project-attachments",
                "tenant-a",
                "ready",
                created_at,
            )],
            project_tenants(),
            object_store.clone(),
        );

        let attachment = service
            .get_attachment("user-1", "attachment-1")
            .await
            .expect("get attachment")
            .expect("attachment exists");
        let response = service
            .delete_attachment(&attachment)
            .await
            .expect("delete attachment");

        assert_eq!(response, AttachmentDeleteResponse::deleted());
        assert!(object_store
            .get("attachments/attachment-1.txt")
            .await
            .expect("read deleted object")
            .is_none());
        assert!(service
            .get_attachment("user-1", "attachment-1")
            .await
            .expect("get deleted attachment")
            .is_none());
    }

    #[tokio::test]
    async fn dev_service_uploads_simple_file_to_storage_and_records_uploaded_row() {
        let object_store = Arc::new(InMemoryObjectStore::new());
        let service = DevAttachmentService::with_object_store(
            Vec::new(),
            project_tenants(),
            object_store.clone(),
        );

        let uploaded = service
            .upload_simple(
                "user-1",
                AttachmentSimpleUpload {
                    conversation_id: "conversation-1".to_string(),
                    project_id: "project-attachments".to_string(),
                    purpose: "both".to_string(),
                    filename: "Report.TXT".to_string(),
                    mime_type: "text/plain".to_string(),
                    bytes: b"hello".to_vec(),
                },
            )
            .await
            .expect("simple upload");

        assert_eq!(uploaded.conversation_id, "conversation-1");
        assert_eq!(uploaded.project_id, "project-attachments");
        assert_eq!(uploaded.filename, "Report.TXT");
        assert_eq!(uploaded.mime_type, "text/plain");
        assert_eq!(uploaded.size_bytes, 5);
        assert_eq!(uploaded.purpose, "both");
        assert_eq!(uploaded.status, "uploaded");
        assert!(uploaded.sandbox_path.is_none());
        assert!(uploaded.error_message.is_none());
        assert!(uploaded
            .object_key
            .starts_with("attachments/tenant-a/project-attachments/conversation-1/"));
        assert!(uploaded.object_key.ends_with(".txt"));
        assert_eq!(
            object_store
                .get(&uploaded.object_key)
                .await
                .expect("read uploaded object")
                .as_deref(),
            Some(&b"hello"[..])
        );
        assert!(service
            .get_attachment("user-1", &uploaded.id)
            .await
            .expect("get uploaded attachment")
            .is_some());
    }

    #[test]
    fn invalid_upload_purpose_matches_python_error() {
        let err = uploaded_record(
            "tenant-a".to_string(),
            AttachmentSimpleUpload {
                conversation_id: "conversation-1".to_string(),
                project_id: "project-attachments".to_string(),
                purpose: "invalid".to_string(),
                filename: "report.txt".to_string(),
                mime_type: "text/plain".to_string(),
                bytes: b"hello".to_vec(),
            },
        )
        .expect_err("invalid purpose should fail");

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "Invalid attachment purpose");
    }

    #[test]
    fn invalid_upload_mime_is_wrapped_like_python_value_error() {
        let err = uploaded_record(
            "tenant-a".to_string(),
            AttachmentSimpleUpload {
                conversation_id: "conversation-1".to_string(),
                project_id: "project-attachments".to_string(),
                purpose: "llm_context".to_string(),
                filename: "archive.bin".to_string(),
                mime_type: "application/octet-stream".to_string(),
                bytes: b"hello".to_vec(),
            },
        )
        .expect_err("invalid mime should fail");

        assert_eq!(err.status, StatusCode::BAD_REQUEST);
        assert_eq!(err.detail, "Invalid upload request");
    }
}
