use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Component, Path as FsPath, PathBuf},
    sync::{Arc, Mutex},
};

use axum::{
    body::Body,
    extract::{Extension, Path, State},
    http::{
        header::{
            CACHE_CONTROL, CONTENT_DISPOSITION, CONTENT_LENGTH, CONTENT_TYPE, ETAG,
            X_CONTENT_TYPE_OPTIONS,
        },
        HeaderMap, HeaderValue, StatusCode,
    },
    response::{IntoResponse, Response},
    routing::get,
    Json, Router,
};
use serde::Deserialize;
use serde_json::json;
use sha2::{Digest, Sha256};
use uuid::Uuid;

use super::super::{
    authority_store::{DesktopArtifactStatus, DesktopArtifactVersion},
    session_store::{DesktopArtifactContentSaveInput, DesktopArtifactContentSaveOutcome},
    AuthenticatedContext, LocalRuntimeState,
};

const CONTRACT_VERSION: u8 = 2;
const MAX_EDITABLE_CONTENT_BYTES: u64 = 1_048_576;
const MAX_ARTIFACT_BYTES: u64 = 50 * 1_048_576;
static ARTIFACT_CONTENT_AUTHORITY_LOCK: Mutex<()> = Mutex::new(());
const EDITABLE_ARTIFACT_MIME_TYPES: &[&str] = &[
    "application/javascript",
    "application/json",
    "application/xml",
    "application/x-yaml",
    "text/css",
    "text/csv",
    "text/html",
    "text/javascript",
    "text/markdown",
    "text/plain",
    "text/x-c",
    "text/x-c++",
    "text/x-go",
    "text/x-java",
    "text/x-php",
    "text/x-python",
    "text/x-ruby",
    "text/x-rust",
    "text/x-shellscript",
    "text/x-typescript",
    "text/xml",
    "text/yaml",
];

pub(super) fn router() -> Router<Arc<LocalRuntimeState>> {
    Router::new()
        .route(
            "/api/v1/artifacts/:artifact_id/content",
            get(get_content).put(save_content),
        )
        .route(
            "/api/v1/artifacts/:artifact_id/content/bytes",
            get(get_content_bytes),
        )
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ArtifactContentSaveCommand {
    contract_version: u8,
    expected_revision: u64,
    content_hash: String,
    idempotency_key: String,
    content: String,
}

struct ResolvedArtifact {
    version: DesktopArtifactVersion,
    path: PathBuf,
}

struct ArtifactContentError {
    status: StatusCode,
    reason_code: &'static str,
    detail: &'static str,
    server_revision: Option<u64>,
    server_content_hash: Option<String>,
}

impl ArtifactContentError {
    fn new(status: StatusCode, reason_code: &'static str, detail: &'static str) -> Self {
        Self {
            status,
            reason_code,
            detail,
            server_revision: None,
            server_content_hash: None,
        }
    }

    fn conflict(
        reason_code: &'static str,
        server_revision: u64,
        server_content_hash: String,
    ) -> Self {
        Self {
            status: StatusCode::CONFLICT,
            reason_code,
            detail: "artifact content authority conflict",
            server_revision: Some(server_revision),
            server_content_hash: Some(server_content_hash),
        }
    }
}

impl IntoResponse for ArtifactContentError {
    fn into_response(self) -> Response {
        (
            self.status,
            Json(json!({
                "contract_version": CONTRACT_VERSION,
                "reason_code": self.reason_code,
                "code": self.reason_code,
                "detail": self.detail,
                "server_revision": self.server_revision,
                "server_content_hash": self.server_content_hash,
            })),
        )
            .into_response()
    }
}

async fn get_content(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_id): Path<String>,
) -> Result<Json<serde_json::Value>, ArtifactContentError> {
    let _authority_guard = ARTIFACT_CONTENT_AUTHORITY_LOCK
        .lock()
        .map_err(|_| internal_error())?;
    let resolved = resolve_artifact(&state, &authenticated, &artifact_id)?;
    let mime_type = editable_mime_type(&resolved.version.mime_type)?;
    let bytes = read_bounded(&resolved.path, MAX_EDITABLE_CONTENT_BYTES)?;
    let content = String::from_utf8(bytes.clone()).map_err(|_| {
        ArtifactContentError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "artifact_content_not_editable",
            "artifact content is not valid UTF-8 text",
        )
    })?;
    let content_hash = content_hash(&bytes);
    let authority = state
        .session_store
        .synchronize_artifact_content_authority(
            &resolved.version,
            &content_hash,
            &super::super::now_iso(),
        )
        .map_err(store_error)?;
    Ok(Json(json!({
        "contract_version": CONTRACT_VERSION,
        "artifact_id": authority.artifact_id,
        "revision": authority.revision,
        "content_hash": authority.content_hash,
        "mime_type": mime_type,
        "content": content,
    })))
}

async fn get_content_bytes(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_id): Path<String>,
) -> Result<Response, ArtifactContentError> {
    let resolved = resolve_artifact(&state, &authenticated, &artifact_id)?;
    let bytes = read_bounded(&resolved.path, MAX_ARTIFACT_BYTES)?;
    let mime_type = normalize_mime_type(&resolved.version.mime_type);
    let content_type = HeaderValue::from_str(&mime_type).map_err(|_| {
        ArtifactContentError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "artifact_mime_type_invalid",
            "artifact MIME type is invalid",
        )
    })?;
    let filename = safe_filename(&resolved.version.filename);
    let disposition = HeaderValue::from_str(&format!("inline; filename=\"{filename}\""))
        .map_err(|_| internal_error())?;
    let etag = HeaderValue::from_str(&format!("\"{}\"", content_hash(&bytes)))
        .map_err(|_| internal_error())?;
    Response::builder()
        .status(StatusCode::OK)
        .header(CONTENT_TYPE, content_type)
        .header(CONTENT_LENGTH, bytes.len().to_string())
        .header(CONTENT_DISPOSITION, disposition)
        .header(CACHE_CONTROL, HeaderValue::from_static("no-store"))
        .header(X_CONTENT_TYPE_OPTIONS, HeaderValue::from_static("nosniff"))
        .header(ETAG, etag)
        .body(Body::from(bytes))
        .map_err(|_| internal_error())
}

async fn save_content(
    State(state): State<Arc<LocalRuntimeState>>,
    Extension(authenticated): Extension<AuthenticatedContext>,
    Path(artifact_id): Path<String>,
    headers: HeaderMap,
    Json(command): Json<ArtifactContentSaveCommand>,
) -> Result<Json<serde_json::Value>, ArtifactContentError> {
    validate_save_command(&command, &headers)?;
    let _authority_guard = ARTIFACT_CONTENT_AUTHORITY_LOCK
        .lock()
        .map_err(|_| internal_error())?;
    let resolved = resolve_artifact(&state, &authenticated, &artifact_id)?;
    if resolved.version.status != DesktopArtifactStatus::Ready {
        return Err(ArtifactContentError::new(
            StatusCode::BAD_REQUEST,
            "artifact_content_not_ready",
            "artifact cannot be updated in its current status",
        ));
    }
    editable_mime_type(&resolved.version.mime_type)?;
    if command.content.len() as u64 > MAX_EDITABLE_CONTENT_BYTES {
        return Err(content_too_large());
    }
    let bytes = command.content.as_bytes();
    let computed_hash = content_hash(bytes);
    if computed_hash != command.content_hash {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_content_hash_mismatch",
            "artifact content hash does not match content",
        ));
    }
    let current_bytes = read_bounded(&resolved.path, MAX_EDITABLE_CONTENT_BYTES)?;
    let observed_content_hash = content_hash(&current_bytes);
    let authority = state
        .session_store
        .synchronize_artifact_content_authority(
            &resolved.version,
            &observed_content_hash,
            &super::super::now_iso(),
        )
        .map_err(store_error)?;
    let request_hash = artifact_save_request_hash(&artifact_id, &command);
    let target_path = resolved.path.clone();
    let save = state
        .session_store
        .save_artifact_content(
            &resolved.version,
            DesktopArtifactContentSaveInput {
                expected_revision: command.expected_revision,
                observed_content_hash: &authority.content_hash,
                content_hash: &command.content_hash,
                idempotency_key: &command.idempotency_key,
                request_hash: &request_hash,
                now: &super::super::now_iso(),
            },
            || atomic_replace(&target_path, bytes),
        )
        .map_err(store_error)?;
    match save {
        DesktopArtifactContentSaveOutcome::Saved(receipt) => Ok(Json(json!({
            "artifact_id": receipt.artifact_id,
            "revision": receipt.revision,
            "content_hash": receipt.content_hash,
            "duplicate": receipt.duplicate,
        }))),
        DesktopArtifactContentSaveOutcome::Conflict {
            reason_code,
            server_revision,
            server_content_hash,
        } => Err(ArtifactContentError::conflict(
            reason_code,
            server_revision,
            server_content_hash,
        )),
    }
}

fn resolve_artifact(
    state: &LocalRuntimeState,
    authenticated: &AuthenticatedContext,
    artifact_id: &str,
) -> Result<ResolvedArtifact, ArtifactContentError> {
    validate_artifact_id(artifact_id)?;
    let version = state
        .session_store
        .current_artifact_version(artifact_id)
        .map_err(store_error)?
        .ok_or_else(artifact_not_found)?;
    let conversation = state
        .session_store
        .conversation(&version.conversation_id)
        .map_err(store_error)?
        .ok_or_else(artifact_not_found)?;
    if conversation.project_id != authenticated.workspace.project_id
        || conversation.tenant_id != authenticated.workspace.tenant_id
    {
        return Err(ArtifactContentError::new(
            StatusCode::FORBIDDEN,
            "artifact_scope_mismatch",
            "artifact is outside the active project scope",
        ));
    }
    let authority_root = match version.run_id.as_deref() {
        Some(run_id) => {
            let run = state
                .session_store
                .run(run_id)
                .map_err(store_error)?
                .ok_or_else(artifact_not_found)?;
            if run.conversation_id != version.conversation_id
                || run.project_id != conversation.project_id
            {
                return Err(artifact_not_found());
            }
            run.environment
                .as_ref()
                .map(|environment| PathBuf::from(&environment.workspace_path))
                .ok_or_else(artifact_not_found)?
        }
        None => state
            .workspace_root
            .lock()
            .map_err(|_| internal_error())?
            .clone(),
    };
    let path = resolve_authority_path(&authority_root, &version)?;
    Ok(ResolvedArtifact { version, path })
}

fn resolve_authority_path(
    authority_root: &FsPath,
    version: &DesktopArtifactVersion,
) -> Result<PathBuf, ArtifactContentError> {
    let root = authority_root
        .canonicalize()
        .map_err(|_| artifact_not_found())?;
    let relative = FsPath::new(&version.relative_path);
    let components = relative.components().collect::<Vec<_>>();
    if components.len() < 4
        || !matches!(components[0], Component::Normal(value) if value == ".agistack")
        || !matches!(components[1], Component::Normal(value) if value == "artifacts")
        || components
            .iter()
            .any(|component| !matches!(component, Component::Normal(_)))
    {
        return Err(artifact_not_found());
    }
    let mut candidate = root.clone();
    for component in components {
        let Component::Normal(segment) = component else {
            return Err(artifact_not_found());
        };
        candidate.push(segment);
        let metadata = fs::symlink_metadata(&candidate).map_err(|_| artifact_not_found())?;
        if metadata.file_type().is_symlink() {
            return Err(ArtifactContentError::new(
                StatusCode::FORBIDDEN,
                "artifact_symlink_not_allowed",
                "artifact path contains a symbolic link",
            ));
        }
    }
    let canonical = candidate.canonicalize().map_err(|_| artifact_not_found())?;
    let persisted = FsPath::new(&version.path)
        .canonicalize()
        .map_err(|_| artifact_not_found())?;
    if canonical != persisted || !canonical.starts_with(root.join(".agistack/artifacts")) {
        return Err(artifact_not_found());
    }
    let metadata = fs::metadata(&canonical).map_err(|_| artifact_not_found())?;
    if !metadata.is_file() {
        return Err(artifact_not_found());
    }
    Ok(canonical)
}

fn validate_save_command(
    command: &ArtifactContentSaveCommand,
    headers: &HeaderMap,
) -> Result<(), ArtifactContentError> {
    if command.contract_version != CONTRACT_VERSION {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_content_contract_unsupported",
            "artifact content contract version is unsupported",
        ));
    }
    if !is_content_hash(&command.content_hash) {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_content_hash_invalid",
            "artifact content hash is invalid",
        ));
    }
    if !is_idempotency_key(&command.idempotency_key) {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_idempotency_key_invalid",
            "artifact idempotency key is invalid",
        ));
    }
    let expected_revision = headers
        .get("x-expected-revision")
        .and_then(|value| value.to_str().ok())
        .and_then(|value| value.parse::<u64>().ok());
    let idempotency_key = headers
        .get("idempotency-key")
        .and_then(|value| value.to_str().ok());
    if expected_revision != Some(command.expected_revision)
        || idempotency_key != Some(command.idempotency_key.as_str())
    {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_authority_headers_invalid",
            "artifact authority headers do not match the save command",
        ));
    }
    Ok(())
}

fn validate_artifact_id(value: &str) -> Result<(), ArtifactContentError> {
    if value.is_empty()
        || value.len() > 256
        || value.contains('/')
        || value.contains('\\')
        || value.chars().any(char::is_control)
    {
        return Err(ArtifactContentError::new(
            StatusCode::UNPROCESSABLE_ENTITY,
            "artifact_id_invalid",
            "artifact id is invalid",
        ));
    }
    Ok(())
}

fn editable_mime_type(value: &str) -> Result<String, ArtifactContentError> {
    let normalized = normalize_mime_type(value);
    if EDITABLE_ARTIFACT_MIME_TYPES.contains(&normalized.as_str()) {
        Ok(normalized)
    } else {
        Err(ArtifactContentError::new(
            StatusCode::UNSUPPORTED_MEDIA_TYPE,
            "artifact_content_not_editable",
            "artifact content is not editable text",
        ))
    }
}

fn normalize_mime_type(value: &str) -> String {
    value
        .split_once(';')
        .map_or(value, |(mime_type, _)| mime_type)
        .trim()
        .to_ascii_lowercase()
}

fn read_bounded(path: &FsPath, limit: u64) -> Result<Vec<u8>, ArtifactContentError> {
    let metadata = fs::metadata(path).map_err(|_| artifact_not_found())?;
    if metadata.len() > limit {
        return Err(content_too_large());
    }
    let mut file = File::open(path).map_err(|_| artifact_not_found())?;
    let mut bytes = Vec::with_capacity(metadata.len() as usize);
    Read::by_ref(&mut file)
        .take(limit.saturating_add(1))
        .read_to_end(&mut bytes)
        .map_err(|_| internal_error())?;
    if bytes.len() as u64 > limit {
        return Err(content_too_large());
    }
    Ok(bytes)
}

fn atomic_replace(path: &FsPath, bytes: &[u8]) -> Result<(), String> {
    let parent = path
        .parent()
        .ok_or_else(|| "artifact parent path is unavailable".to_string())?;
    let filename = path
        .file_name()
        .and_then(|value| value.to_str())
        .ok_or_else(|| "artifact filename is invalid".to_string())?;
    let temp_path = parent.join(format!(".{filename}.agistack-{}.tmp", Uuid::new_v4()));
    let result = (|| {
        let mut temp = OpenOptions::new()
            .create_new(true)
            .write(true)
            .open(&temp_path)
            .map_err(|error| error.to_string())?;
        if let Ok(metadata) = fs::metadata(path) {
            fs::set_permissions(&temp_path, metadata.permissions())
                .map_err(|error| error.to_string())?;
        }
        temp.write_all(bytes).map_err(|error| error.to_string())?;
        temp.sync_all().map_err(|error| error.to_string())?;
        drop(temp);
        fs::rename(&temp_path, path).map_err(|error| error.to_string())?;
        File::open(parent)
            .and_then(|directory| directory.sync_all())
            .map_err(|error| error.to_string())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temp_path);
    }
    result
}

fn artifact_save_request_hash(artifact_id: &str, command: &ArtifactContentSaveCommand) -> String {
    let mut digest = Sha256::new();
    for value in [
        "artifact-content-v2",
        artifact_id,
        &command.expected_revision.to_string(),
        &command.content_hash,
        &command.content,
    ] {
        digest.update(value.as_bytes());
        digest.update(b"\0");
    }
    format!("sha256:{:x}", digest.finalize())
}

fn content_hash(bytes: &[u8]) -> String {
    format!("sha256:{:x}", Sha256::digest(bytes))
}

fn is_content_hash(value: &str) -> bool {
    value.len() == 71
        && value.strip_prefix("sha256:").is_some_and(|digest| {
            digest
                .bytes()
                .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
        })
}

fn is_idempotency_key(value: &str) -> bool {
    (8..=128).contains(&value.len())
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'.' | b'_' | b':' | b'-'))
}

fn safe_filename(value: &str) -> String {
    let sanitized = value
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
        "artifact".to_string()
    } else {
        sanitized
    }
}

fn artifact_not_found() -> ArtifactContentError {
    ArtifactContentError::new(
        StatusCode::NOT_FOUND,
        "artifact_not_found",
        "artifact was not found",
    )
}

fn content_too_large() -> ArtifactContentError {
    ArtifactContentError::new(
        StatusCode::PAYLOAD_TOO_LARGE,
        "artifact_content_too_large",
        "artifact content exceeds the allowed byte limit",
    )
}

fn internal_error() -> ArtifactContentError {
    ArtifactContentError::new(
        StatusCode::INTERNAL_SERVER_ERROR,
        "artifact_content_io_error",
        "artifact content operation failed",
    )
}

fn store_error(_error: String) -> ArtifactContentError {
    internal_error()
}
