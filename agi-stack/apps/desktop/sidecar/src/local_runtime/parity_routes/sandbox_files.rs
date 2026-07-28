use std::{
    fs::{self, File, Metadata},
    io::Read,
    path::{Component, Path as FsPath, PathBuf},
    sync::Arc,
    time::UNIX_EPOCH,
};

use axum::{
    body::Body,
    extract::{rejection::QueryRejection, Extension, Path, Query, State},
    http::{
        header::{
            CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE, ETAG,
            X_CONTENT_TYPE_OPTIONS,
        },
        HeaderValue, StatusCode,
    },
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde::{Deserialize, Serialize};
use serde_json::json;
use sha2::{Digest, Sha256};

use super::super::{ensure_active_project, AuthenticatedContext, LocalRuntimeState};

const CONTRACT_VERSION: u8 = 1;
const AUTHORITY: &str = "native_workspace";
const ISOLATION: &str = "not_applicable";
const VIRTUAL_ROOT: &str = "/workspace";
const DEFAULT_LIST_LIMIT: usize = 200;
const MAX_LIST_LIMIT: usize = 500;
const DEFAULT_READ_LIMIT: u64 = 1_048_576;
const MAX_READ_LIMIT: u64 = 1_048_576;
const DEFAULT_DOWNLOAD_LIMIT: u64 = 25 * 1_048_576;
const MAX_DOWNLOAD_LIMIT: u64 = 25 * 1_048_576;

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/projects/:project_id/sandbox/files",
            get(list_files),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/files/content",
            get(read_file),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/files/download",
            get(download_file),
        )
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ListFilesQuery {
    path: String,
    limit: Option<usize>,
    cursor: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadFileQuery {
    path: String,
    max_bytes: Option<u64>,
}

#[derive(Serialize)]
struct FileEntry {
    path: String,
    name: String,
    kind: &'static str,
    size_bytes: Option<u64>,
    mime_type: Option<&'static str>,
    #[serde(skip_serializing)]
    revision_marker: u128,
}

#[derive(Clone)]
struct WorkspaceAuthority {
    root: PathBuf,
}

struct ResolvedPath {
    virtual_path: String,
    canonical_path: PathBuf,
    metadata: Metadata,
}

struct SandboxFileError {
    status: StatusCode,
    reason_code: &'static str,
    detail: &'static str,
}

impl SandboxFileError {
    fn new(status: StatusCode, reason_code: &'static str, detail: &'static str) -> Self {
        Self {
            status,
            reason_code,
            detail,
        }
    }
}

impl IntoResponse for SandboxFileError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "contract_version": CONTRACT_VERSION,
                "authority": AUTHORITY,
                "isolation": ISOLATION,
                "reason_code": self.reason_code,
                "code": self.reason_code,
                "detail": self.detail,
            })),
        )
            .into_response()
    }
}

async fn list_files(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    query: Result<Query<ListFilesQuery>, QueryRejection>,
) -> Result<Json<serde_json::Value>, SandboxFileError> {
    ensure_project_scope(&authenticated, &project_id)?;
    let Query(query) = query.map_err(|_| malformed_query())?;
    let limit = query.limit.unwrap_or(DEFAULT_LIST_LIMIT);
    if !(1..=MAX_LIST_LIMIT).contains(&limit) {
        return Err(SandboxFileError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "sandbox_file_limit_invalid",
            "sandbox file list limit is invalid",
        ));
    }
    let cursor = query.cursor.as_deref().map(validate_cursor).transpose()?;
    let authority = WorkspaceAuthority::from_state(&state)?;
    let resolved = authority.resolve(&query.path)?;
    if !resolved.metadata.is_dir() {
        return Err(unsupported_file_type());
    }

    let mut entries = authority.list_directory(&resolved)?;
    entries.sort_by(|left, right| left.name.cmp(&right.name));
    let revision = listing_revision(&entries);
    if let Some(cursor) = cursor {
        entries.retain(|entry| entry.name.as_str() > cursor);
    }
    let has_more = entries.len() > limit;
    entries.truncate(limit);
    let next_cursor = has_more
        .then(|| entries.last().map(|entry| entry.name.clone()))
        .flatten();

    Ok(Json(json!({
        "contract_version": CONTRACT_VERSION,
        "authority": AUTHORITY,
        "isolation": ISOLATION,
        "path": resolved.virtual_path,
        "entries": entries,
        "cursor": next_cursor,
        "revision": revision,
    })))
}

async fn read_file(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    query: Result<Query<ReadFileQuery>, QueryRejection>,
) -> Result<Json<serde_json::Value>, SandboxFileError> {
    ensure_project_scope(&authenticated, &project_id)?;
    let Query(query) = query.map_err(|_| malformed_query())?;
    let max_bytes = validated_max_bytes(
        query.max_bytes.unwrap_or(DEFAULT_READ_LIMIT),
        MAX_READ_LIMIT,
    )?;
    let authority = WorkspaceAuthority::from_state(&state)?;
    let resolved = authority.resolve(&query.path)?;
    let mime_type = readable_mime_type(&resolved.canonical_path)?;
    let bytes = read_bounded(&resolved, max_bytes)?;
    let content = String::from_utf8(bytes.clone()).map_err(|_| {
        SandboxFileError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "sandbox_file_text_read_unsupported",
            "sandbox file is not valid UTF-8 text",
        )
    })?;
    let revision = content_revision(&bytes);

    Ok(Json(json!({
        "contract_version": CONTRACT_VERSION,
        "authority": AUTHORITY,
        "isolation": ISOLATION,
        "path": resolved.virtual_path,
        "encoding": "utf-8",
        "content": content,
        "mime_type": mime_type,
        "size_bytes": bytes.len(),
        "revision": revision,
        "truncated": false,
    })))
}

async fn download_file(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(project_id): Path<String>,
    query: Result<Query<ReadFileQuery>, QueryRejection>,
) -> Result<Response, SandboxFileError> {
    ensure_project_scope(&authenticated, &project_id)?;
    let Query(query) = query.map_err(|_| malformed_query())?;
    let max_bytes = validated_max_bytes(
        query.max_bytes.unwrap_or(DEFAULT_DOWNLOAD_LIMIT),
        MAX_DOWNLOAD_LIMIT,
    )?;
    let authority = WorkspaceAuthority::from_state(&state)?;
    let resolved = authority.resolve(&query.path)?;
    let bytes = read_bounded(&resolved, max_bytes)?;
    let revision = content_revision(&bytes);
    let mime_type = mime_type(&resolved.canonical_path);
    let filename = safe_download_filename(&resolved.canonical_path);
    let disposition = HeaderValue::from_str(&format!("attachment; filename=\"{filename}\""))
        .map_err(|_| internal_error())?;
    let etag = HeaderValue::from_str(&format!("\"{revision}\"")).map_err(|_| internal_error())?;

    Response::builder()
        .status(StatusCode::OK)
        .header(CONTENT_TYPE, HeaderValue::from_static(mime_type))
        .header(CONTENT_LENGTH, bytes.len().to_string())
        .header(CONTENT_DISPOSITION, disposition)
        .header(CACHE_CONTROL, HeaderValue::from_static("no-store"))
        .header(X_CONTENT_TYPE_OPTIONS, HeaderValue::from_static("nosniff"))
        .header(
            "x-memstack-file-contract-version",
            HeaderValue::from_static("1"),
        )
        .header(
            "x-memstack-file-authority",
            HeaderValue::from_static(AUTHORITY),
        )
        .header(
            "x-memstack-file-isolation",
            HeaderValue::from_static(ISOLATION),
        )
        .header(
            "access-control-expose-headers",
            HeaderValue::from_static(
                "Content-Disposition, Content-Length, ETag, \
                 X-MemStack-File-Contract-Version, X-MemStack-File-Authority, \
                 X-MemStack-File-Isolation",
            ),
        )
        .header(ETAG, etag)
        .body(Body::from(bytes))
        .map_err(|_| internal_error())
}

impl WorkspaceAuthority {
    fn from_state(state: &LocalRuntimeState) -> Result<Self, SandboxFileError> {
        let configured = state
            .workspace_root
            .lock()
            .map_err(|_| workspace_unavailable())?
            .clone();
        let root = configured
            .canonicalize()
            .map_err(|_| workspace_unavailable())?;
        if !root.is_dir() {
            return Err(workspace_unavailable());
        }
        Ok(Self { root })
    }

    fn resolve(&self, input: &str) -> Result<ResolvedPath, SandboxFileError> {
        let (virtual_path, segments) = parse_virtual_path(input)?;
        let mut candidate = self.root.clone();
        for segment in segments {
            candidate.push(segment);
            let metadata = fs::symlink_metadata(&candidate).map_err(map_not_found)?;
            if metadata.file_type().is_symlink() {
                return Err(SandboxFileError::new(
                    StatusCode::FORBIDDEN,
                    "sandbox_file_symlink_not_allowed",
                    "sandbox file path contains a symbolic link",
                ));
            }
        }
        let canonical_path = candidate.canonicalize().map_err(map_not_found)?;
        if !canonical_path.starts_with(&self.root) {
            return Err(SandboxFileError::new(
                StatusCode::FORBIDDEN,
                "sandbox_file_path_outside_workspace",
                "sandbox file path is outside the native workspace",
            ));
        }
        let metadata = fs::symlink_metadata(&canonical_path).map_err(map_not_found)?;
        Ok(ResolvedPath {
            virtual_path,
            canonical_path,
            metadata,
        })
    }

    fn list_directory(&self, directory: &ResolvedPath) -> Result<Vec<FileEntry>, SandboxFileError> {
        let mut entries = Vec::new();
        let children = fs::read_dir(&directory.canonical_path).map_err(|_| internal_error())?;
        for child in children {
            let child = child.map_err(|_| internal_error())?;
            let metadata = fs::symlink_metadata(child.path()).map_err(|_| internal_error())?;
            if metadata.file_type().is_symlink() || (!metadata.is_file() && !metadata.is_dir()) {
                continue;
            }
            let canonical = child.path().canonicalize().map_err(|_| internal_error())?;
            if !canonical.starts_with(&self.root) {
                continue;
            }
            let Some(name) = child.file_name().to_str().map(ToString::to_string) else {
                continue;
            };
            if directory.virtual_path == VIRTUAL_ROOT && is_reserved_top_level_entry(&name) {
                continue;
            }
            let virtual_path = join_virtual_path(&directory.virtual_path, &name);
            entries.push(FileEntry {
                path: virtual_path,
                name,
                kind: if metadata.is_dir() {
                    "directory"
                } else {
                    "file"
                },
                size_bytes: metadata.is_file().then_some(metadata.len()),
                mime_type: metadata.is_file().then(|| mime_type(&canonical)),
                revision_marker: metadata
                    .modified()
                    .ok()
                    .and_then(|modified| modified.duration_since(UNIX_EPOCH).ok())
                    .map(|duration| duration.as_nanos())
                    .unwrap_or_default(),
            });
        }
        Ok(entries)
    }
}

fn parse_virtual_path(input: &str) -> Result<(String, Vec<&str>), SandboxFileError> {
    if input == VIRTUAL_ROOT || input == format!("{VIRTUAL_ROOT}/") {
        return Ok((VIRTUAL_ROOT.to_string(), Vec::new()));
    }
    let Some(relative) = input.strip_prefix(&format!("{VIRTUAL_ROOT}/")) else {
        return Err(invalid_path());
    };
    if relative.is_empty() || input.contains('\\') || input.chars().any(char::is_control) {
        return Err(invalid_path());
    }
    let segments = relative.split('/').collect::<Vec<_>>();
    if segments.iter().any(|segment| {
        segment.is_empty()
            || *segment == "."
            || *segment == ".."
            || !matches!(
                FsPath::new(segment)
                    .components()
                    .collect::<Vec<_>>()
                    .as_slice(),
                [Component::Normal(_)]
            )
    }) {
        return Err(invalid_path());
    }
    if segments
        .first()
        .is_some_and(|segment| is_reserved_top_level_entry(segment))
    {
        return Err(SandboxFileError::new(
            StatusCode::FORBIDDEN,
            "sandbox_file_reserved_path",
            "sandbox file path is reserved for the local runtime",
        ));
    }
    Ok((format!("{VIRTUAL_ROOT}/{relative}"), segments))
}

fn validate_cursor(input: &str) -> Result<&str, SandboxFileError> {
    if input.is_empty()
        || input.len() > 255
        || input.contains('/')
        || input.contains('\\')
        || input.chars().any(char::is_control)
    {
        return Err(SandboxFileError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "sandbox_file_cursor_invalid",
            "sandbox file cursor is invalid",
        ));
    }
    Ok(input)
}

fn validated_max_bytes(input: u64, maximum: u64) -> Result<u64, SandboxFileError> {
    if input == 0 || input > maximum {
        return Err(SandboxFileError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "sandbox_file_limit_invalid",
            "sandbox file byte limit is invalid",
        ));
    }
    Ok(input)
}

fn read_bounded(resolved: &ResolvedPath, max_bytes: u64) -> Result<Vec<u8>, SandboxFileError> {
    if !resolved.metadata.is_file() {
        return Err(unsupported_file_type());
    }
    if resolved.metadata.len() > max_bytes {
        return Err(file_too_large());
    }
    let mut file = File::open(&resolved.canonical_path).map_err(|_| internal_error())?;
    let mut bytes = Vec::with_capacity(resolved.metadata.len() as usize);
    file.by_ref()
        .take(max_bytes.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|_| internal_error())?;
    if bytes.len() as u64 > max_bytes {
        return Err(file_too_large());
    }
    Ok(bytes)
}

fn readable_mime_type(path: &FsPath) -> Result<&'static str, SandboxFileError> {
    let mime = mime_type(path);
    if mime.starts_with("text/")
        || matches!(
            mime,
            "application/json"
                | "application/javascript"
                | "application/toml"
                | "application/xml"
                | "application/yaml"
        )
    {
        Ok(mime)
    } else {
        Err(SandboxFileError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "sandbox_file_text_read_unsupported",
            "sandbox file MIME type is not supported by the text reader",
        ))
    }
}

fn mime_type(path: &FsPath) -> &'static str {
    match path
        .extension()
        .and_then(|extension| extension.to_str())
        .map(str::to_ascii_lowercase)
        .as_deref()
    {
        Some("txt" | "log") => "text/plain",
        Some("md" | "markdown") => "text/markdown",
        Some("csv") => "text/csv",
        Some("html" | "htm") => "text/html",
        Some("css") => "text/css",
        Some("json" | "map") => "application/json",
        Some("js" | "mjs" | "cjs") => "application/javascript",
        Some("xml") => "application/xml",
        Some("yaml" | "yml") => "application/yaml",
        Some("toml") => "application/toml",
        Some("pdf") => "application/pdf",
        Some("svg") => "image/svg+xml",
        Some("png") => "image/png",
        Some("jpg" | "jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        Some("mp3") => "audio/mpeg",
        Some("wav") => "audio/wav",
        Some("mp4") => "video/mp4",
        Some("webm") => "video/webm",
        Some("docx") => "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        Some("xlsx") => "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        _ => "application/octet-stream",
    }
}

fn safe_download_filename(path: &FsPath) -> String {
    let candidate = path
        .file_name()
        .and_then(|name| name.to_str())
        .unwrap_or("download");
    let sanitized = candidate
        .chars()
        .map(|character| {
            if character.is_ascii_alphanumeric() || matches!(character, '.' | '_' | '-') {
                character
            } else {
                '_'
            }
        })
        .collect::<String>();
    if sanitized.is_empty() {
        "download".to_string()
    } else {
        sanitized
    }
}

fn listing_revision(entries: &[FileEntry]) -> String {
    let mut digest = Sha256::new();
    for entry in entries {
        digest.update(entry.path.as_bytes());
        digest.update([0]);
        digest.update(entry.kind.as_bytes());
        digest.update([0]);
        digest.update(entry.size_bytes.unwrap_or_default().to_le_bytes());
        digest.update([0]);
        digest.update(entry.revision_marker.to_le_bytes());
        digest.update([0]);
        if let Some(mime_type) = entry.mime_type {
            digest.update(mime_type.as_bytes());
        }
        digest.update([0xff]);
    }
    format!("sha256:{:x}", digest.finalize())
}

fn content_revision(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn join_virtual_path(parent: &str, name: &str) -> String {
    if parent == VIRTUAL_ROOT {
        format!("{VIRTUAL_ROOT}/{name}")
    } else {
        format!("{parent}/{name}")
    }
}

fn is_reserved_top_level_entry(name: &str) -> bool {
    name.eq_ignore_ascii_case(".agistack")
}

fn ensure_project_scope(
    authenticated: &AuthenticatedContext,
    project_id: &str,
) -> Result<(), SandboxFileError> {
    ensure_active_project(authenticated, project_id).map_err(|_| {
        SandboxFileError::new(
            StatusCode::FORBIDDEN,
            "sandbox_file_scope_mismatch",
            "sandbox file request is outside the active project",
        )
    })
}

fn malformed_query() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::UNPROCESSABLE_ENTITY,
        "sandbox_file_query_invalid",
        "sandbox file query is invalid",
    )
}

fn invalid_path() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::UNPROCESSABLE_ENTITY,
        "sandbox_file_path_invalid",
        "sandbox file path is invalid",
    )
}

fn map_not_found(error: std::io::Error) -> SandboxFileError {
    if error.kind() == std::io::ErrorKind::NotFound {
        SandboxFileError::new(
            StatusCode::NOT_FOUND,
            "sandbox_file_not_found",
            "sandbox file was not found",
        )
    } else {
        internal_error()
    }
}

fn unsupported_file_type() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::UNPROCESSABLE_ENTITY,
        "sandbox_file_type_unsupported",
        "sandbox file type is not supported",
    )
}

fn file_too_large() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::PAYLOAD_TOO_LARGE,
        "sandbox_file_too_large",
        "sandbox file exceeds the allowed byte limit",
    )
}

fn workspace_unavailable() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::SERVICE_UNAVAILABLE,
        "native_workspace_unavailable",
        "native workspace is unavailable",
    )
}

fn internal_error() -> SandboxFileError {
    SandboxFileError::new(
        StatusCode::INTERNAL_SERVER_ERROR,
        "sandbox_file_io_error",
        "sandbox file operation failed",
    )
}
