//! Tenant-scoped legacy File HTTP handlers over external object storage.

use std::io;
use std::path::PathBuf;
use std::pin::Pin;
use std::sync::Arc;
use std::task::{Context, Poll};

use axum::body::Body;
use axum::extract::multipart::MultipartRejection;
use axum::extract::rejection::JsonRejection;
use axum::extract::{DefaultBodyLimit, Multipart, Path, Query};
use axum::http::{HeaderMap, HeaderValue, StatusCode, header};
use axum::response::{IntoResponse, Response};
use axum::routing::{get, post};
use axum::{Extension, Json, Router};
use bcs_storage_api::{ByteStream, ByteStreamTrait};
use bytes::Bytes;
use futures::Stream;
use memstack_workspace_service::{
    PublicWorkspaceFile, PublicWorkspaceFileContext, PublicWorkspaceFileError,
    PublicWorkspaceFileErrorKind, PublicWorkspaceFileService,
};
use serde::Deserialize;
use serde_json::{Map, Value, json};
use sha2::{Digest, Sha256};
use tokio::fs::{File, OpenOptions};
use tokio::io::AsyncWriteExt;
use tokio_util::io::ReaderStream;
use uuid::Uuid;

use super::creation::{body_validation_error, map_public_json_rejection, optional_header};
use super::public_api::caller_from_headers;
use super::{ApiError, WorkspaceCoreState};

const IDEMPOTENCY_HEADER: &str = "idempotency-key";
const IF_MATCH_HEADER: &str = "if-match";
const USER_EMAIL_HEADER: &str = "x-memstack-user-email";
const ACTOR_TYPE_HEADER: &str = "x-memstack-actor-type";
const ACTOR_ID_HEADER: &str = "x-memstack-actor-id";
const MAX_FILE_SIZE: u64 = 100 * 1024 * 1024;
const MAX_MULTIPART_BODY_SIZE: usize = 102 * 1024 * 1024;

#[derive(Debug, Deserialize)]
struct FileListQuery {
    parent_path: Option<String>,
}

#[derive(Debug, Deserialize)]
struct FileDeleteQuery {
    recursive: Option<String>,
}

pub(super) fn router() -> Router {
    Router::new()
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files",
            get(list_files),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/mkdir",
            post(create_directory),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/upload",
            post(upload_file),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}",
            axum::routing::patch(patch_file).delete(delete_file),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}/copy",
            post(copy_file),
        )
        .route(
            "/api/v1/tenants/{tenant_id}/projects/{project_id}/workspaces/{workspace_id}/blackboard/files/{file_id}/download",
            get(download_file),
        )
        .layer(DefaultBodyLimit::max(MAX_MULTIPART_BODY_SIZE))
}

async fn list_files(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    Query(query): Query<FileListQuery>,
    headers: HeaderMap,
) -> FileResult<Json<Value>> {
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let items = service(&state)
        .list(&context, query.parent_path.as_deref().unwrap_or("/"))
        .await
        .map_err(map_file_error)?;
    Ok(Json(json!({"items": items})))
}

async fn create_directory(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> FileResult<(StatusCode, Json<PublicWorkspaceFile>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let parent_path = optional_text(fields, "parent_path", None)?.unwrap_or_else(|| "/".into());
    let name = required_text(fields, "name", &request, Some(255))?;
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let outcome = service(&state)
        .create_directory(&context, parent_path.as_str(), name.as_str())
        .await
        .map_err(map_file_error)?;
    Ok((StatusCode::CREATED, Json(outcome.file)))
}

async fn upload_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id)): Path<(String, String, String)>,
    headers: HeaderMap,
    multipart: Result<Multipart, MultipartRejection>,
) -> FileResult<(StatusCode, Json<PublicWorkspaceFile>)> {
    let multipart = multipart.map_err(map_multipart_rejection)?;
    let staged = stage_multipart(multipart).await?;
    let body = staged.byte_stream().await?;
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let result = service(&state)
        .upload(
            &context,
            staged.parent_path.as_str(),
            staged.filename.as_str(),
            staged.content_type.as_str(),
            staged.size_bytes,
            staged.checksum_sha256.as_str(),
            body,
        )
        .await;
    staged.cleanup().await;
    let outcome = result.map_err(map_file_error)?;
    Ok((StatusCode::CREATED, Json(outcome.file)))
}

async fn download_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
) -> FileResult<Response> {
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let download = service(&state)
        .download(&context, file_id.as_str())
        .await
        .map_err(map_file_error)?;
    let etag = download.checksum_sha256.as_ref().map_or_else(
        || {
            format!(
                "W/\"sz-{}-id-{}\"",
                download.file.file_size, download.file.id
            )
        },
        |checksum| format!("\"{checksum}\""),
    );
    if etag_matches(&headers, etag.as_str()) {
        return Ok((
            StatusCode::NOT_MODIFIED,
            [(header::ETAG, HeaderValue::from_str(etag.as_str())?)],
        )
            .into_response());
    }

    let content_type = HeaderValue::from_str(download.file.content_type.as_str())
        .unwrap_or_else(|_| HeaderValue::from_static("application/octet-stream"));
    let disposition = HeaderValue::from_str(
        format!(
            "attachment; filename=\"{}\"",
            quoted_filename(download.file.name.as_str())
        )
        .as_str(),
    )?;
    let mut response = Response::new(Body::from_stream(download.body));
    response
        .headers_mut()
        .insert(header::CONTENT_TYPE, content_type);
    response.headers_mut().insert(
        header::CONTENT_LENGTH,
        HeaderValue::from_str(download.file.file_size.to_string().as_str())?,
    );
    response
        .headers_mut()
        .insert(header::CONTENT_DISPOSITION, disposition);
    response.headers_mut().insert(
        header::CACHE_CONTROL,
        HeaderValue::from_static("private, no-cache"),
    );
    response
        .headers_mut()
        .insert(header::ETAG, HeaderValue::from_str(etag.as_str())?);
    response
        .headers_mut()
        .insert(header::ACCEPT_RANGES, HeaderValue::from_static("bytes"));
    Ok(response)
}

async fn patch_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> FileResult<Json<PublicWorkspaceFile>> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let name = optional_text(fields, "name", Some(255))?;
    let parent_path = optional_text(fields, "parent_path", None)?;
    if name.is_none() && parent_path.is_none() {
        return Err(FileHttpError::response(
            StatusCode::BAD_REQUEST,
            "Provide at least one of 'name' or 'parent_path'",
        ));
    }
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let outcome = service(&state)
        .patch(
            &context,
            file_id.as_str(),
            name.as_deref(),
            parent_path.as_deref(),
        )
        .await
        .map_err(map_file_error)?;
    Ok(Json(outcome.file))
}

async fn copy_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    headers: HeaderMap,
    request: Result<Json<Value>, JsonRejection>,
) -> FileResult<(StatusCode, Json<PublicWorkspaceFile>)> {
    let Json(request) = request.map_err(map_public_json_rejection)?;
    let fields = request_object(&request)?;
    let target_parent = required_text(fields, "target_parent_path", &request, None)?;
    let name = optional_text(fields, "name", Some(255))?;
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let outcome = service(&state)
        .copy(
            &context,
            file_id.as_str(),
            target_parent.as_str(),
            name.as_deref(),
        )
        .await
        .map_err(map_file_error)?;
    Ok((StatusCode::CREATED, Json(outcome.file)))
}

async fn delete_file(
    Extension(state): Extension<Arc<WorkspaceCoreState>>,
    Path((tenant_id, project_id, workspace_id, file_id)): Path<(String, String, String, String)>,
    Query(query): Query<FileDeleteQuery>,
    headers: HeaderMap,
) -> FileResult<Json<Value>> {
    let recursive = query
        .recursive
        .as_deref()
        .map(parse_query_bool)
        .transpose()?
        .unwrap_or(false);
    let context = file_context(tenant_id, project_id, workspace_id, &headers)?;
    let outcome = service(&state)
        .delete(&context, file_id.as_str(), recursive)
        .await
        .map_err(map_file_error)?;
    Ok(Json(outcome.response))
}

fn service(state: &WorkspaceCoreState) -> PublicWorkspaceFileService<'_> {
    PublicWorkspaceFileService::new(
        state.db.as_ref(),
        state.sql_flavor,
        Arc::clone(&state.object_store),
    )
}

fn file_context(
    tenant_id: String,
    project_id: String,
    workspace_id: String,
    headers: &HeaderMap,
) -> FileResult<PublicWorkspaceFileContext> {
    let caller = caller_from_headers(headers)?;
    let user_name =
        optional_header(headers, USER_EMAIL_HEADER)?.unwrap_or_else(|| caller.user_id.clone());
    let uploader_type =
        optional_header(headers, ACTOR_TYPE_HEADER)?.unwrap_or_else(|| "user".to_string());
    if !matches!(uploader_type.as_str(), "user" | "agent") {
        return Err(FileHttpError::response(
            StatusCode::BAD_REQUEST,
            "Invalid Workspace File uploader type",
        ));
    }
    let uploader_id =
        optional_header(headers, ACTOR_ID_HEADER)?.unwrap_or_else(|| caller.user_id.clone());
    let uploader_actor_id = format!("{uploader_type}:{uploader_id}");
    Ok(PublicWorkspaceFileContext {
        tenant_id,
        project_id,
        workspace_id,
        user_id: caller.user_id.clone(),
        user_name,
        uploader_type,
        uploader_id: uploader_id.clone(),
        uploader_actor_id,
        expected_revision: optional_header(headers, IF_MATCH_HEADER)?
            .map(|value| parse_if_match(value.as_str()))
            .transpose()?,
        idempotency_key: optional_header(headers, IDEMPOTENCY_HEADER)?,
    })
}

fn parse_if_match(value: &str) -> FileResult<u64> {
    let value = value.trim();
    let value = value.strip_prefix("W/").unwrap_or(value);
    let value = value
        .strip_prefix('"')
        .and_then(|value| value.strip_suffix('"'))
        .unwrap_or(value);
    value.parse::<u64>().map_err(|_| {
        FileHttpError::response(
            StatusCode::BAD_REQUEST,
            "If-Match must contain a non-negative Workspace revision",
        )
    })
}

fn parse_query_bool(value: &str) -> FileResult<bool> {
    match value.trim().to_ascii_lowercase().as_str() {
        "true" | "1" | "on" | "yes" => Ok(true),
        "false" | "0" | "off" | "no" => Ok(false),
        _ => Err(ApiError::Validation(json!([{
            "type": "bool_parsing",
            "loc": ["query", "recursive"],
            "msg": "Input should be a valid boolean",
            "input": value,
        }]))
        .into()),
    }
}

fn request_object(request: &Value) -> FileResult<&Map<String, Value>> {
    request.as_object().ok_or_else(|| {
        body_validation_error(
            "model_attributes_type",
            None,
            "Input should be a valid dictionary or object to extract fields from",
            request.clone(),
            None,
        )
        .into()
    })
}

fn required_text(
    fields: &Map<String, Value>,
    field: &'static str,
    request: &Value,
    max_chars: Option<usize>,
) -> FileResult<String> {
    let value = fields.get(field).ok_or_else(|| {
        body_validation_error(
            "missing",
            Some(field),
            "Field required",
            request.clone(),
            None,
        )
    })?;
    let value = value.as_str().ok_or_else(|| {
        body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
    })?;
    validate_text(field, value, max_chars)?;
    Ok(value.to_string())
}

fn optional_text(
    fields: &Map<String, Value>,
    field: &'static str,
    max_chars: Option<usize>,
) -> FileResult<Option<String>> {
    match fields.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) => {
            validate_text(field, value, max_chars)?;
            Ok(Some(value.clone()))
        }
        Some(value) => Err(body_validation_error(
            "string_type",
            Some(field),
            "Input should be a valid string",
            value.clone(),
            None,
        )
        .into()),
    }
}

fn validate_text(field: &'static str, value: &str, max_chars: Option<usize>) -> FileResult<()> {
    let chars = value.chars().count();
    if chars == 0 {
        return Err(body_validation_error(
            "string_too_short",
            Some(field),
            "String should have at least 1 character",
            Value::String(value.to_string()),
            Some(json!({"min_length": 1})),
        )
        .into());
    }
    if max_chars.is_some_and(|maximum| chars > maximum) {
        let maximum = max_chars.unwrap_or_default();
        return Err(body_validation_error(
            "string_too_long",
            Some(field),
            format!("String should have at most {maximum} characters").as_str(),
            Value::String(value.to_string()),
            Some(json!({"max_length": maximum})),
        )
        .into());
    }
    Ok(())
}

pub(super) async fn stage_multipart(mut multipart: Multipart) -> FileResult<StagedUpload> {
    let mut parent_path = "/".to_string();
    let mut staged: Option<StagedUpload> = None;
    while let Some(mut field) = multipart.next_field().await.map_err(multipart_error)? {
        match field.name() {
            Some("parent_path") => {
                let value = field.text().await.map_err(multipart_error)?;
                if value.chars().count() > 1024 {
                    return Err(FileHttpError::response(
                        StatusCode::BAD_REQUEST,
                        "Workspace File parent path is too long",
                    ));
                }
                parent_path = value;
            }
            Some("file") => {
                if staged.is_some() {
                    return Err(FileHttpError::response(
                        StatusCode::BAD_REQUEST,
                        "Only one Workspace File may be uploaded per request",
                    ));
                }
                let filename = field.file_name().unwrap_or("unnamed").to_string();
                let content_type = field
                    .content_type()
                    .unwrap_or("application/octet-stream")
                    .to_string();
                let (path, mut file) = create_staging_file().await?;
                let stage_result: FileResult<(u64, String)> = async {
                    let mut size_bytes = 0_u64;
                    let mut hasher = Sha256::new();
                    while let Some(chunk) = field.chunk().await.map_err(multipart_error)? {
                        size_bytes = size_bytes
                            .checked_add(u64::try_from(chunk.len()).map_err(|_| {
                                FileHttpError::response(
                                    StatusCode::PAYLOAD_TOO_LARGE,
                                    "Workspace File upload exceeds platform size",
                                )
                            })?)
                            .ok_or_else(|| {
                                FileHttpError::response(
                                    StatusCode::PAYLOAD_TOO_LARGE,
                                    "Workspace File upload exceeds platform size",
                                )
                            })?;
                        if size_bytes > MAX_FILE_SIZE {
                            return Err(FileHttpError::response(
                                StatusCode::PAYLOAD_TOO_LARGE,
                                "Workspace File exceeds the 100 MiB limit",
                            ));
                        }
                        hasher.update(&chunk);
                        file.write_all(&chunk).await.map_err(staging_io_error)?;
                    }
                    file.flush().await.map_err(staging_io_error)?;
                    Ok((size_bytes, hex::encode(hasher.finalize())))
                }
                .await;
                drop(file);
                let (size_bytes, checksum_sha256) = match stage_result {
                    Ok(result) => result,
                    Err(error) => {
                        cleanup_staging_path(&path).await;
                        return Err(error);
                    }
                };
                staged = Some(StagedUpload {
                    path,
                    parent_path: String::new(),
                    filename,
                    content_type,
                    size_bytes,
                    checksum_sha256,
                    cleaned: false,
                });
            }
            _ => {
                return Err(FileHttpError::response(
                    StatusCode::BAD_REQUEST,
                    "Unexpected Workspace File multipart field",
                ));
            }
        }
    }
    let mut staged = staged.ok_or_else(|| {
        body_validation_error("missing", Some("file"), "Field required", Value::Null, None)
    })?;
    staged.parent_path = parent_path;
    Ok(staged)
}

async fn create_staging_file() -> FileResult<(PathBuf, File)> {
    for _ in 0..4 {
        let path =
            std::env::temp_dir().join(format!("memstack-workspace-upload-{}", Uuid::new_v4()));
        match OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&path)
            .await
        {
            Ok(file) => return Ok((path, file)),
            Err(error) if error.kind() == io::ErrorKind::AlreadyExists => {}
            Err(error) => return Err(staging_io_error(error)),
        }
    }
    Err(FileHttpError::response(
        StatusCode::SERVICE_UNAVAILABLE,
        "Workspace File staging is unavailable",
    ))
}

pub(super) struct StagedUpload {
    path: PathBuf,
    pub(super) parent_path: String,
    pub(super) filename: String,
    pub(super) content_type: String,
    pub(super) size_bytes: u64,
    pub(super) checksum_sha256: String,
    cleaned: bool,
}

impl StagedUpload {
    pub(super) async fn byte_stream(&self) -> FileResult<ByteStream> {
        let file = File::open(&self.path).await.map_err(staging_io_error)?;
        Ok(Box::new(FileByteStream(ReaderStream::new(file))))
    }

    pub(super) async fn cleanup(mut self) {
        self.cleaned = cleanup_staging_path(&self.path).await;
    }
}

async fn cleanup_staging_path(path: &PathBuf) -> bool {
    match tokio::fs::remove_file(path).await {
        Ok(()) => true,
        Err(error) if error.kind() == io::ErrorKind::NotFound => true,
        Err(error) => {
            tracing::warn!(path = %path.display(), error = %error, "Workspace File staging cleanup failed");
            false
        }
    }
}

impl Drop for StagedUpload {
    fn drop(&mut self) {
        if !self.cleaned {
            let _ = std::fs::remove_file(&self.path);
        }
    }
}

struct FileByteStream(ReaderStream<File>);

impl Stream for FileByteStream {
    type Item = Result<Bytes, io::Error>;

    fn poll_next(mut self: Pin<&mut Self>, context: &mut Context<'_>) -> Poll<Option<Self::Item>> {
        Pin::new(&mut self.0).poll_next(context)
    }
}

impl ByteStreamTrait for FileByteStream {}

fn etag_matches(headers: &HeaderMap, etag: &str) -> bool {
    headers
        .get(header::IF_NONE_MATCH)
        .and_then(|value| value.to_str().ok())
        .is_some_and(|value| value.split(',').any(|candidate| candidate.trim() == etag))
}

fn quoted_filename(filename: &str) -> String {
    filename
        .chars()
        .filter(|character| !character.is_control())
        .flat_map(|character| match character {
            '"' => ['\\', '"'].into_iter().take(2),
            '\\' => ['\\', '\\'].into_iter().take(2),
            other => [other, '\0'].into_iter().take(1),
        })
        .collect()
}

fn map_file_error(error: PublicWorkspaceFileError) -> FileHttpError {
    match error.kind() {
        PublicWorkspaceFileErrorKind::InvalidRequest => {
            FileHttpError::response(StatusCode::BAD_REQUEST, "Invalid blackboard request")
        }
        PublicWorkspaceFileErrorKind::NotFound => {
            FileHttpError::response(StatusCode::NOT_FOUND, "Blackboard item not found")
        }
        PublicWorkspaceFileErrorKind::Forbidden => {
            FileHttpError::response(StatusCode::FORBIDDEN, "Access denied")
        }
        PublicWorkspaceFileErrorKind::Conflict => {
            FileHttpError::response(StatusCode::CONFLICT, "Workspace File authority conflict")
        }
        PublicWorkspaceFileErrorKind::Unavailable => FileHttpError::response(
            StatusCode::SERVICE_UNAVAILABLE,
            "Workspace File authority is unavailable",
        ),
    }
}

fn map_multipart_rejection(error: MultipartRejection) -> FileHttpError {
    ApiError::Validation(json!([{
        "type": "multipart_type",
        "loc": ["body"],
        "msg": "Input should be valid multipart form data",
        "input": error.to_string(),
    }]))
    .into()
}

fn multipart_error(error: axum::extract::multipart::MultipartError) -> FileHttpError {
    FileHttpError::response(StatusCode::BAD_REQUEST, error.to_string())
}

fn staging_io_error(error: io::Error) -> FileHttpError {
    tracing::error!(error = %error, "Workspace File staging I/O failed");
    FileHttpError::response(
        StatusCode::SERVICE_UNAVAILABLE,
        "Workspace File staging is unavailable",
    )
}

pub(super) type FileResult<T> = Result<T, FileHttpError>;

#[derive(Debug)]
pub(super) enum FileHttpError {
    Core(ApiError),
    Response(StatusCode, String),
}

impl FileHttpError {
    fn response(status: StatusCode, detail: impl Into<String>) -> Self {
        Self::Response(status, detail.into())
    }
}

impl From<ApiError> for FileHttpError {
    fn from(error: ApiError) -> Self {
        Self::Core(error)
    }
}

impl From<header::InvalidHeaderValue> for FileHttpError {
    fn from(error: header::InvalidHeaderValue) -> Self {
        tracing::error!(error = %error, "Workspace File response header is invalid");
        Self::response(
            StatusCode::INTERNAL_SERVER_ERROR,
            "Workspace File response is invalid",
        )
    }
}

impl IntoResponse for FileHttpError {
    fn into_response(self) -> Response {
        match self {
            Self::Core(error) => error.into_response(),
            Self::Response(status, detail) => {
                (status, Json(json!({"detail": detail}))).into_response()
            }
        }
    }
}
