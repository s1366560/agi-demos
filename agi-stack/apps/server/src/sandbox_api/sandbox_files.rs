use std::sync::Arc;
use std::time::Duration;

use axum::{
    body::Body,
    extract::{FromRef, Path, Query, State},
    http::{
        header::{CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE},
        HeaderValue, StatusCode,
    },
    response::{IntoResponse, Response},
    routing::get,
    Extension, Json, Router,
};
use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use serde::Deserialize;
use serde_json::{json, Map, Value};
use sha2::{Digest, Sha256};

use super::*;
use crate::auth::SharedAuthenticator;
use crate::identity::SharedIdentity;

const LIST_TOOL: &str = "platform_list_workspace_files";
const READ_TOOL: &str = "platform_read_workspace_file";
const DOWNLOAD_TOOL: &str = "platform_download_workspace_file";
const MAX_PATH_BYTES: usize = 4_096;
const MAX_CURSOR_BYTES: usize = 256;
const MAX_LIST_ITEMS: usize = 500;
const DEFAULT_LIST_ITEMS: usize = 200;
const MAX_READ_BYTES: usize = 1_048_576;
const MAX_DOWNLOAD_BYTES: usize = 25 * 1_048_576;
const FILE_TOOL_TIMEOUT: Duration = Duration::from_secs(15);
const MAX_TOOL_RESULT_BYTES: usize = 36 * 1_048_576;

const LISTING_KEYS: &[&str] = &[
    "authority",
    "contract_version",
    "cursor",
    "entries",
    "isolation",
    "path",
    "revision",
    "root",
];
const ENTRY_KEYS: &[&str] = &["kind", "mime_type", "name", "path", "size_bytes"];
const CONTENT_KEYS: &[&str] = &[
    "authority",
    "content",
    "contract_version",
    "encoding",
    "isolation",
    "mime_type",
    "path",
    "revision",
    "size_bytes",
    "truncated",
];
const DOWNLOAD_KEYS: &[&str] = &[
    "authority",
    "base64",
    "contract_version",
    "filename",
    "isolation",
    "mime_type",
    "path",
    "sha256",
    "size_bytes",
];

#[derive(Clone)]
pub(super) struct SandboxFilesState {
    auth: SharedAuthenticator,
    identity: SharedIdentity,
    sandboxes: SharedProjectSandboxes,
}

impl SandboxFilesState {
    #[cfg(test)]
    pub(super) fn new(
        auth: SharedAuthenticator,
        identity: SharedIdentity,
        sandboxes: SharedProjectSandboxes,
    ) -> Self {
        Self {
            auth,
            identity,
            sandboxes,
        }
    }
}

impl FromRef<AppState> for SandboxFilesState {
    fn from_ref(app: &AppState) -> Self {
        Self {
            auth: Arc::clone(&app.auth),
            identity: Arc::clone(&app.identity),
            sandboxes: Arc::clone(&app.sandboxes),
        }
    }
}

#[derive(Debug)]
struct SandboxFileError {
    status: StatusCode,
    reason_code: &'static str,
}

impl SandboxFileError {
    const fn new(status: StatusCode, reason_code: &'static str) -> Self {
        Self {
            status,
            reason_code,
        }
    }
}

impl IntoResponse for SandboxFileError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({ "detail": { "reason_code": self.reason_code } })),
        )
            .into_response()
    }
}

type SandboxFileResult<T> = Result<T, SandboxFileError>;

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ListFilesQuery {
    #[serde(default = "default_root_path")]
    path: String,
    #[serde(default = "default_list_limit")]
    limit: usize,
    cursor: Option<String>,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct ReadFileQuery {
    path: String,
    #[serde(default = "default_read_limit")]
    max_bytes: usize,
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
struct DownloadFileQuery {
    path: String,
    #[serde(default = "default_download_limit")]
    max_bytes: usize,
}

fn default_root_path() -> String {
    "/".to_string()
}

const fn default_list_limit() -> usize {
    DEFAULT_LIST_ITEMS
}

const fn default_read_limit() -> usize {
    MAX_READ_BYTES
}

const fn default_download_limit() -> usize {
    MAX_DOWNLOAD_BYTES
}

pub(super) fn router<S>() -> Router<S>
where
    S: Clone + Send + Sync + 'static,
    SandboxFilesState: FromRef<S>,
{
    Router::new()
        .route(
            "/api/v1/projects/:project_id/sandbox/files",
            get(list_project_sandbox_files),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/files/content",
            get(read_project_sandbox_file),
        )
        .route(
            "/api/v1/projects/:project_id/sandbox/files/download",
            get(download_project_sandbox_file),
        )
}

impl ProjectSandboxService {
    pub(super) fn file_authority_available(&self) -> bool {
        self.tool_connector.is_some()
            || self
                .tool_host
                .as_ref()
                .is_some_and(|host| file_tools_available(host.as_ref()))
    }

    async fn execute_file_tool(
        &self,
        project_id: &str,
        expected_tenant_id: &str,
        tool_name: &'static str,
        arguments: &Value,
    ) -> SandboxFileResult<Value> {
        let info = self
            .get(project_id)
            .await
            .map_err(|_| runtime_unavailable())?
            .ok_or_else(runtime_unavailable)?;
        if info.tenant_id != expected_tenant_id {
            return Err(scope_forbidden());
        }
        if !info.healthy() {
            return Err(runtime_unavailable());
        }

        let endpoint = info.websocket_url.as_ref().or(info.endpoint.as_ref());
        let host = match (endpoint, self.tool_connector.as_ref()) {
            (Some(url), Some(connector)) => connector
                .connect_tool_host(url)
                .await
                .map_err(|_| runtime_unavailable())?,
            _ => self.tool_host.clone().ok_or_else(runtime_unavailable)?,
        };
        if !host.list_tools().iter().any(|name| name == tool_name) {
            return Err(runtime_unavailable());
        }

        let raw = tokio::time::timeout(
            FILE_TOOL_TIMEOUT,
            host.call(tool_name, &arguments.to_string()),
        )
        .await
        .map_err(|_| runtime_unavailable())?
        .map_err(|_| runtime_unavailable())?;
        if raw.len() > MAX_TOOL_RESULT_BYTES {
            return Err(contract_invalid());
        }
        let parsed = serde_json::from_str::<Value>(&raw).map_err(|_| contract_invalid())?;
        if !parsed.is_object() {
            return Err(contract_invalid());
        }
        Ok(parsed)
    }
}

fn file_tools_available(host: &dyn ToolHost) -> bool {
    let tools = host.list_tools();
    [LIST_TOOL, READ_TOOL, DOWNLOAD_TOOL]
        .iter()
        .all(|required| tools.iter().any(|tool| tool == required))
}

async fn project_tenant_scope(
    state: &SandboxFilesState,
    identity: &Identity,
    project_id: &str,
) -> SandboxFileResult<String> {
    let allowed = state
        .auth
        .can_write_project(&identity.user_id, project_id)
        .await
        .map_err(|_| runtime_unavailable())?;
    if !allowed {
        return Err(scope_forbidden());
    }
    state
        .identity
        .get_project(&identity.user_id, project_id, None)
        .await
        .map(|project| project.tenant_id)
        .map_err(|error| {
            if error.status.is_server_error() {
                runtime_unavailable()
            } else {
                scope_forbidden()
            }
        })
}

async fn list_project_sandbox_files(
    State(state): State<SandboxFilesState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<ListFilesQuery>,
) -> SandboxFileResult<Response> {
    let tenant_id = project_tenant_scope(&state, &identity, &project_id).await?;
    let path = validated_path(&query.path)?;
    if query.limit == 0 || query.limit > MAX_LIST_ITEMS {
        return Err(reason_error("sandbox_file_limit_invalid"));
    }
    if query
        .cursor
        .as_ref()
        .is_some_and(|cursor| cursor.is_empty() || cursor.len() > MAX_CURSOR_BYTES)
    {
        return Err(reason_error("sandbox_file_cursor_invalid"));
    }
    let result = state
        .sandboxes
        .execute_file_tool(
            &project_id,
            &tenant_id,
            LIST_TOOL,
            &json!({
                "path": path,
                "limit": query.limit,
                "cursor": query.cursor,
            }),
        )
        .await?;
    let payload = success_payload(result, "listing", path)?;
    validate_listing(&payload, query.limit)?;
    Ok(Json(payload).into_response())
}

async fn read_project_sandbox_file(
    State(state): State<SandboxFilesState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<ReadFileQuery>,
) -> SandboxFileResult<Response> {
    let tenant_id = project_tenant_scope(&state, &identity, &project_id).await?;
    let path = validated_path(&query.path)?;
    if query.max_bytes == 0 || query.max_bytes > MAX_READ_BYTES {
        return Err(reason_error("sandbox_file_limit_invalid"));
    }
    let result = state
        .sandboxes
        .execute_file_tool(
            &project_id,
            &tenant_id,
            READ_TOOL,
            &json!({ "path": path, "max_bytes": query.max_bytes }),
        )
        .await?;
    let payload = success_payload(result, "file", path)?;
    validate_content(&payload, query.max_bytes)?;
    Ok(Json(payload).into_response())
}

async fn download_project_sandbox_file(
    State(state): State<SandboxFilesState>,
    Extension(identity): Extension<Identity>,
    Path(project_id): Path<String>,
    Query(query): Query<DownloadFileQuery>,
) -> SandboxFileResult<Response> {
    let tenant_id = project_tenant_scope(&state, &identity, &project_id).await?;
    let path = validated_path(&query.path)?;
    if query.max_bytes == 0 || query.max_bytes > MAX_DOWNLOAD_BYTES {
        return Err(reason_error("sandbox_file_limit_invalid"));
    }
    let result = state
        .sandboxes
        .execute_file_tool(
            &project_id,
            &tenant_id,
            DOWNLOAD_TOOL,
            &json!({ "path": path, "max_bytes": query.max_bytes }),
        )
        .await?;
    let payload = success_payload(result, "download", path)?;
    let download = validate_download(&payload, query.max_bytes)?;
    download_response(download)
}

fn validated_path(path: &str) -> SandboxFileResult<&str> {
    let invalid = path.is_empty()
        || path.len() > MAX_PATH_BYTES
        || !path.starts_with('/')
        || path.contains('\0')
        || path.contains('\\')
        || path.split('/').any(|segment| matches!(segment, "." | ".."));
    if invalid {
        Err(reason_error("sandbox_file_path_invalid"))
    } else {
        Ok(path)
    }
}

fn success_payload(result: Value, key: &str, expected_path: &str) -> SandboxFileResult<Value> {
    let object = result.as_object().ok_or_else(contract_invalid)?;
    if !object.get("content").is_some_and(Value::is_array) {
        return Err(contract_invalid());
    }
    let is_error = tool_error_flag(object)?;
    if is_error {
        let reason_code = object
            .get("reason_code")
            .and_then(Value::as_str)
            .unwrap_or("sandbox_file_tool_failed");
        return Err(reason_error(reason_code));
    }
    let payload = object.get(key).cloned().ok_or_else(contract_invalid)?;
    let payload_object = payload.as_object().ok_or_else(contract_invalid)?;
    if payload_object
        .get("contract_version")
        .and_then(Value::as_u64)
        != Some(1)
        || payload_object.get("authority").and_then(Value::as_str) != Some("sandbox")
        || payload_object.get("isolation").and_then(Value::as_str) != Some("isolated")
        || payload_object.get("path").and_then(Value::as_str) != Some(expected_path)
    {
        return Err(contract_invalid());
    }
    Ok(payload)
}

fn tool_error_flag(object: &Map<String, Value>) -> SandboxFileResult<bool> {
    match (object.get("isError"), object.get("is_error")) {
        (Some(camel), None) | (None, Some(camel)) => camel.as_bool().ok_or_else(contract_invalid),
        (Some(camel), Some(snake)) => match (camel.as_bool(), snake.as_bool()) {
            (Some(left), Some(right)) if left == right => Ok(left),
            _ => Err(contract_invalid()),
        },
        (None, None) => Err(contract_invalid()),
    }
}

fn validate_listing(payload: &Value, limit: usize) -> SandboxFileResult<()> {
    let object = exact_object(payload, LISTING_KEYS)?;
    if object.get("root").and_then(Value::as_str) != Some("/")
        || !is_sha256(object.get("revision").and_then(Value::as_str))
    {
        return Err(contract_invalid());
    }
    if let Some(cursor) = object.get("cursor").and_then(Value::as_str) {
        if cursor.is_empty() || cursor.len() > MAX_CURSOR_BYTES {
            return Err(contract_invalid());
        }
    } else if !object.get("cursor").is_some_and(Value::is_null) {
        return Err(contract_invalid());
    }
    let entries = object
        .get("entries")
        .and_then(Value::as_array)
        .ok_or_else(contract_invalid)?;
    if entries.len() > limit {
        return Err(contract_invalid());
    }
    for entry in entries {
        let entry = exact_object(entry, ENTRY_KEYS)?;
        let path = entry
            .get("path")
            .and_then(Value::as_str)
            .ok_or_else(contract_invalid)?;
        validated_path(path).map_err(|_| contract_invalid())?;
        let name = entry
            .get("name")
            .and_then(Value::as_str)
            .ok_or_else(contract_invalid)?;
        if name.is_empty()
            || name.contains('/')
            || name.contains('\\')
            || name.chars().any(char::is_control)
        {
            return Err(contract_invalid());
        }
        match entry.get("kind").and_then(Value::as_str) {
            Some("directory")
                if entry.get("size_bytes").is_some_and(Value::is_null)
                    && entry.get("mime_type").is_some_and(Value::is_null) => {}
            Some("file") => {
                if entry.get("size_bytes").and_then(Value::as_u64).is_none()
                    || !is_mime_type(entry.get("mime_type").and_then(Value::as_str))
                {
                    return Err(contract_invalid());
                }
            }
            _ => return Err(contract_invalid()),
        }
    }
    Ok(())
}

fn validate_content(payload: &Value, max_bytes: usize) -> SandboxFileResult<()> {
    let object = exact_object(payload, CONTENT_KEYS)?;
    let content = object
        .get("content")
        .and_then(Value::as_str)
        .ok_or_else(contract_invalid)?;
    let size_bytes = object
        .get("size_bytes")
        .and_then(Value::as_u64)
        .and_then(|size| usize::try_from(size).ok())
        .ok_or_else(contract_invalid)?;
    if object.get("encoding").and_then(Value::as_str) != Some("utf-8")
        || size_bytes != content.len()
        || size_bytes > max_bytes
        || !is_mime_type(object.get("mime_type").and_then(Value::as_str))
        || !is_sha256(object.get("revision").and_then(Value::as_str))
        || object.get("truncated").and_then(Value::as_bool).is_none()
    {
        return Err(contract_invalid());
    }
    Ok(())
}

struct ValidatedDownload {
    bytes: Vec<u8>,
    filename: String,
    mime_type: String,
}

fn validate_download(payload: &Value, max_bytes: usize) -> SandboxFileResult<ValidatedDownload> {
    let object = exact_object(payload, DOWNLOAD_KEYS)?;
    let filename = object
        .get("filename")
        .and_then(Value::as_str)
        .filter(|name| {
            !name.is_empty()
                && !name.contains('/')
                && !name.contains('\\')
                && !name.chars().any(char::is_control)
        })
        .ok_or_else(contract_invalid)?;
    let mime_type = object
        .get("mime_type")
        .and_then(Value::as_str)
        .filter(|value| is_mime_type(Some(value)))
        .ok_or_else(contract_invalid)?;
    let size_bytes = object
        .get("size_bytes")
        .and_then(Value::as_u64)
        .and_then(|size| usize::try_from(size).ok())
        .filter(|size| *size <= max_bytes)
        .ok_or_else(contract_invalid)?;
    let encoded = object
        .get("base64")
        .and_then(Value::as_str)
        .filter(|encoded| encoded.len() <= max_base64_len(max_bytes))
        .ok_or_else(contract_invalid)?;
    let expected_hash = object
        .get("sha256")
        .and_then(Value::as_str)
        .filter(|value| is_sha256(Some(value)))
        .ok_or_else(contract_invalid)?;
    let bytes = BASE64_STANDARD
        .decode(encoded)
        .map_err(|_| contract_invalid())?;
    if bytes.len() != size_bytes
        || bytes.len() > max_bytes
        || format!("{:x}", Sha256::digest(&bytes)) != expected_hash
    {
        return Err(contract_invalid());
    }
    Ok(ValidatedDownload {
        bytes,
        filename: filename.to_string(),
        mime_type: mime_type.to_string(),
    })
}

fn download_response(download: ValidatedDownload) -> SandboxFileResult<Response> {
    let content_length = download.bytes.len();
    let filename_ascii = if download.filename.is_ascii() {
        download.filename.as_str()
    } else {
        "download"
    };
    let disposition = format!(
        "attachment; filename=\"{}\"; filename*=UTF-8''{}",
        filename_ascii,
        percent_encode_filename(&download.filename)
    );
    let mut response = Response::new(Body::from(download.bytes));
    let headers = response.headers_mut();
    headers.insert(
        CONTENT_TYPE,
        HeaderValue::from_str(&download.mime_type).map_err(|_| contract_invalid())?,
    );
    headers.insert(
        CONTENT_DISPOSITION,
        HeaderValue::from_str(&disposition).map_err(|_| contract_invalid())?,
    );
    headers.insert(CACHE_CONTROL, HeaderValue::from_static("no-store"));
    headers.insert(
        CONTENT_LENGTH,
        HeaderValue::from_str(&content_length.to_string()).map_err(|_| contract_invalid())?,
    );
    headers.insert(
        "x-memstack-file-contract-version",
        HeaderValue::from_static("1"),
    );
    headers.insert(
        "x-memstack-file-authority",
        HeaderValue::from_static("sandbox"),
    );
    headers.insert(
        "x-memstack-file-isolation",
        HeaderValue::from_static("isolated"),
    );
    Ok(response)
}

fn exact_object<'a>(
    value: &'a Value,
    expected_keys: &[&str],
) -> SandboxFileResult<&'a Map<String, Value>> {
    let object = value.as_object().ok_or_else(contract_invalid)?;
    if object.len() != expected_keys.len()
        || !expected_keys.iter().all(|key| object.contains_key(*key))
    {
        return Err(contract_invalid());
    }
    Ok(object)
}

fn is_sha256(value: Option<&str>) -> bool {
    value.is_some_and(|value| {
        value.len() == 64
            && value
                .as_bytes()
                .iter()
                .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
    })
}

fn is_mime_type(value: Option<&str>) -> bool {
    let Some(value) = value else {
        return false;
    };
    let mut parts = value.split('/');
    let Some(kind) = parts.next() else {
        return false;
    };
    let Some(subtype) = parts.next() else {
        return false;
    };
    parts.next().is_none()
        && mime_token_valid(kind.as_bytes())
        && mime_token_valid(subtype.as_bytes())
}

fn mime_token_valid(value: &[u8]) -> bool {
    !value.is_empty()
        && value.iter().all(|byte| {
            byte.is_ascii_lowercase()
                || byte.is_ascii_digit()
                || matches!(
                    byte,
                    b'!' | b'#' | b'$' | b'&' | b'^' | b'_' | b'.' | b'+' | b'-'
                )
        })
}

const fn max_base64_len(max_bytes: usize) -> usize {
    max_bytes.div_ceil(3) * 4
}

fn percent_encode_filename(value: &str) -> String {
    const HEX: &[u8; 16] = b"0123456789ABCDEF";
    let mut output = String::with_capacity(value.len());
    for byte in value.bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'.' | b'_' | b'~') {
            output.push(char::from(byte));
        } else {
            output.push('%');
            output.push(char::from(HEX[usize::from(byte >> 4)]));
            output.push(char::from(HEX[usize::from(byte & 0x0f)]));
        }
    }
    output
}

fn reason_error(reason_code: &str) -> SandboxFileError {
    match reason_code {
        "sandbox_file_path_invalid" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_path_invalid")
        }
        "sandbox_file_limit_invalid" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_limit_invalid")
        }
        "sandbox_file_cursor_invalid" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_cursor_invalid")
        }
        "sandbox_file_symlink_rejected" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_symlink_rejected")
        }
        "sandbox_file_not_directory" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_not_directory")
        }
        "sandbox_file_not_file" => {
            SandboxFileError::new(StatusCode::BAD_REQUEST, "sandbox_file_not_file")
        }
        "sandbox_file_not_found" => {
            SandboxFileError::new(StatusCode::NOT_FOUND, "sandbox_file_not_found")
        }
        "sandbox_file_cursor_stale" => {
            SandboxFileError::new(StatusCode::CONFLICT, "sandbox_file_cursor_stale")
        }
        "sandbox_file_too_large" => {
            SandboxFileError::new(StatusCode::PAYLOAD_TOO_LARGE, "sandbox_file_too_large")
        }
        "sandbox_file_mime_not_text" => SandboxFileError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "sandbox_file_mime_not_text",
        ),
        "sandbox_file_encoding_invalid" => SandboxFileError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "sandbox_file_encoding_invalid",
        ),
        "sandbox_file_io_error" => {
            SandboxFileError::new(StatusCode::BAD_GATEWAY, "sandbox_file_io_error")
        }
        _ => SandboxFileError::new(StatusCode::BAD_GATEWAY, "sandbox_file_tool_failed"),
    }
}

const fn contract_invalid() -> SandboxFileError {
    SandboxFileError::new(StatusCode::BAD_GATEWAY, "sandbox_file_contract_invalid")
}

const fn runtime_unavailable() -> SandboxFileError {
    SandboxFileError::new(StatusCode::BAD_GATEWAY, "sandbox_file_runtime_unavailable")
}

const fn scope_forbidden() -> SandboxFileError {
    SandboxFileError::new(StatusCode::FORBIDDEN, "sandbox_file_scope_forbidden")
}
