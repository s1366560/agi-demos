//! Request-scoped, read-only workspace capabilities for signed project operations.
use cap_fs_ext::{DirExt, FollowSymlinks, OpenOptionsFollowExt};
use cap_std::fs::{Dir, OpenOptions};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{
    io::Read,
    path::{Component, Path as FsPath, PathBuf},
    time::UNIX_EPOCH,
};

const VIRTUAL_ROOT: &str = "/workspace";

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Plan {
    operation: Operation,
    body: Value,
    contract: serde_json::Map<String, Value>,
    download_headers: Vec<(String, String)>,
    errors: std::collections::BTreeMap<String, (u16, String, String)>,
}

#[derive(Clone, Copy, Deserialize)]
#[serde(rename_all = "snake_case")]
enum Operation {
    Status,
    Directory,
    Text,
    Download,
}

impl Operation {
    fn permission(self) -> &'static str {
        match self {
            Self::Status => "device.workspace.read.status",
            Self::Directory => "device.workspace.read.directory",
            Self::Text => "device.workspace.read.text",
            Self::Download => "device.workspace.read.download",
        }
    }
}

impl Plan {
    pub(super) fn permission(&self) -> &'static str {
        self.operation.permission()
    }
    pub(super) async fn respond(
        self,
        root: PathBuf,
        uri: axum::http::Uri,
        head: bool,
    ) -> axum::response::Response {
        use axum::response::IntoResponse;
        static READS: tokio::sync::Semaphore = tokio::sync::Semaphore::const_new(4);
        let Ok(permit) = READS.acquire().await else {
            return axum::http::StatusCode::SERVICE_UNAVAILABLE.into_response();
        };
        let mut response = tokio::task::spawn_blocking(move || {
            let _permit = permit;
            match self.read(&root, &uri) {
                Ok(response) => response,
                Err(key) => {
                    let Some((status, code, detail)) = self.errors.get(key) else {
                        return axum::http::StatusCode::BAD_GATEWAY.into_response();
                    };
                    let mut fields = self.contract;
                    fields.extend([
                        ("reason_code".into(), json!(code)),
                        ("code".into(), json!(code)),
                        ("detail".into(), json!(detail)),
                    ]);
                    (
                        axum::http::StatusCode::from_u16(*status)
                            .ok()
                            .filter(|s| s.is_client_error() || s.is_server_error())
                            .unwrap_or(axum::http::StatusCode::BAD_GATEWAY),
                        axum::Json(fields),
                    )
                        .into_response()
                }
            }
        })
        .await
        .unwrap_or_else(|_| axum::http::StatusCode::INTERNAL_SERVER_ERROR.into_response());
        if head {
            *response.body_mut() = axum::body::Body::empty();
        }
        response
    }

    fn read(
        &self,
        root: &FsPath,
        uri: &axum::http::Uri,
    ) -> Result<axum::response::Response, &'static str> {
        use axum::{extract::Query, response::IntoResponse};
        let dir = open_root(root)?;
        let value = match self.operation {
            Operation::Status => {
                let mut status = self.body.clone();
                if status.get("service_version") == Some(&json!("$host_version")) {
                    status["service_version"] = json!(env!("CARGO_PKG_VERSION"));
                }
                return Ok(axum::Json(status).into_response());
            }
            Operation::Directory => {
                let Query(query) =
                    Query::<ListFilesQuery>::try_from_uri(uri).map_err(|_| "query")?;
                let limit = query.limit.unwrap_or(200);
                if !(1..=500).contains(&limit) {
                    return Err("list_limit");
                }
                let cursor = query.cursor.as_deref().map(validate_cursor).transpose()?;
                let (path, segments) = parse_virtual_path(&query.path)?;
                let directory = open_directory(dir, &segments)?;
                let mut entries = Vec::new();
                for child in directory.entries().map_err(|_| "io")? {
                    let child = child.map_err(|_| "io")?;
                    let Ok(name) = child.file_name().into_string() else {
                        continue;
                    };
                    if path == VIRTUAL_ROOT && is_reserved_top_level_entry(&name) {
                        continue;
                    }
                    let metadata = directory.symlink_metadata(&name).map_err(|_| "io")?;
                    if !metadata.is_dir() && !metadata.is_file() {
                        continue;
                    }
                    entries.push(FileEntry {
                        path: join_virtual_path(&path, &name),
                        kind: if metadata.is_dir() {
                            "directory"
                        } else {
                            "file"
                        },
                        size_bytes: metadata.is_file().then_some(metadata.len()),
                        mime_type: metadata.is_file().then(|| mime_type(FsPath::new(&name))),
                        revision_marker: metadata
                            .modified()
                            .ok()
                            .and_then(|t| t.into_std().duration_since(UNIX_EPOCH).ok())
                            .map(|d| d.as_nanos())
                            .unwrap_or_default(),
                        name,
                    });
                }
                entries.sort_by(|a, b| a.name.cmp(&b.name));
                let revision = listing_revision(&entries);
                if let Some(cursor) = cursor {
                    entries.retain(|e| e.name.as_str() > cursor)
                }
                let more = entries.len() > limit;
                entries.truncate(limit);
                let cursor = more
                    .then(|| entries.last().map(|e| e.name.clone()))
                    .flatten();
                json!({"path":path,"entries":entries,"cursor":cursor,"revision":revision})
            }
            op @ (Operation::Text | Operation::Download) => {
                let Query(query) =
                    Query::<ReadFileQuery>::try_from_uri(uri).map_err(|_| "query")?;
                let maximum = if matches!(op, Operation::Text) {
                    1_048_576
                } else {
                    25 * 1_048_576
                };
                let limit = query.max_bytes.unwrap_or(maximum);
                if !(1..=maximum).contains(&limit) {
                    return Err("bytes_limit");
                }
                let (path, segments) = parse_virtual_path(&query.path)?;
                let (name, parents) = segments.split_last().ok_or("type")?;
                let parent = open_directory(dir, parents)?;
                let info = parent.symlink_metadata(name).map_err(io_error)?;
                if info.file_type().is_symlink() {
                    return Err("symlink");
                }
                if !info.is_file() {
                    return Err("type");
                }
                let mime = if matches!(op, Operation::Text) {
                    readable_mime_type(FsPath::new(name))?
                } else {
                    mime_type(FsPath::new(name))
                };
                let mut options = OpenOptions::new();
                options.read(true).follow(FollowSymlinks::No);
                #[cfg(unix)]
                {
                    use cap_std::fs::OpenOptionsExt;
                    options.custom_flags(libc::O_NONBLOCK);
                }
                let file = parent.open_with(name, &options).map_err(io_error)?;
                let meta = file.metadata().map_err(|_| "io")?;
                if !meta.is_file() {
                    return Err("type");
                }
                if meta.len() > limit {
                    return Err("too_large");
                }
                let mut bytes = Vec::with_capacity(meta.len() as usize);
                file.take(limit + 1)
                    .read_to_end(&mut bytes)
                    .map_err(|_| "io")?;
                if bytes.len() as u64 > limit {
                    return Err("too_large");
                }
                let revision = content_revision(&bytes);
                if matches!(op, Operation::Download) {
                    return self.download(bytes, name, mime, &revision);
                }
                let length = bytes.len();
                json!({"path":path,"content":String::from_utf8(bytes).map_err(|_|"encoding")?,"revision":revision,"size_bytes":length,"mime_type":mime,"encoding":"utf-8","truncated":false})
            }
        };
        let mut merged = self.contract.clone();
        if let Value::Object(fields) = value {
            merged.extend(fields)
        }
        Ok(axum::Json(merged).into_response())
    }

    fn download(
        &self,
        bytes: Vec<u8>,
        name: &str,
        mime: &str,
        revision: &str,
    ) -> Result<axum::response::Response, &'static str> {
        let filename = safe_download_filename(FsPath::new(name));
        let mut reply = axum::response::Response::builder()
            .header("content-type", mime)
            .header("content-length", bytes.len())
            .header(
                "content-disposition",
                format!("attachment; filename=\"{filename}\""),
            )
            .header("cache-control", "no-store")
            .header("x-content-type-options", "nosniff")
            .header("etag", format!("\"{revision}\""));
        let mut exposed = vec![
            "Content-Disposition".into(),
            "Content-Length".into(),
            "ETag".into(),
        ];
        for (key, value) in &self.download_headers {
            if !key.to_ascii_lowercase().starts_with("x-memstack-file-")
                || key.len() > 80
                || value.len() > 128
            {
                return Err("io");
            }
            reply = reply.header(key, value);
            exposed.push(key.to_string());
        }
        reply
            .header("access-control-expose-headers", exposed.join(", "))
            .body(axum::body::Body::from(bytes))
            .map_err(|_| "io")
    }
}
fn open_root(root: &FsPath) -> Result<Dir, &'static str> {
    // The configured absolute path was canonicalized at grant time. Reopen its
    // components relative to directory handles, denying later symlink substitution.
    if !root.is_absolute() {
        return Err("root");
    }
    let mut ancestors = root.ancestors().collect::<Vec<_>>().into_iter().rev();
    let anchor = ancestors.next().ok_or("root")?;
    let mut dir =
        Dir::open_ambient_dir(anchor, cap_std::ambient_authority()).map_err(|_| "root")?;
    for path in ancestors {
        dir = dir
            .open_dir_nofollow(path.file_name().ok_or("root")?)
            .map_err(|_| "root")?;
    }
    Ok(dir)
}

fn io_error(e: std::io::Error) -> &'static str {
    if e.kind() == std::io::ErrorKind::NotFound {
        "not_found"
    } else {
        "io"
    }
}

fn open_directory(mut dir: Dir, parts: &[&str]) -> Result<Dir, &'static str> {
    for part in parts {
        let metadata = dir.symlink_metadata(part).map_err(io_error)?;
        if metadata.file_type().is_symlink() {
            return Err("symlink");
        }
        if !metadata.is_dir() {
            return Err("type");
        }
        dir = dir.open_dir_nofollow(part).map_err(io_error)?;
    }
    Ok(dir)
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

fn parse_virtual_path(input: &str) -> Result<(String, Vec<&str>), &'static str> {
    if input == VIRTUAL_ROOT || input == format!("{VIRTUAL_ROOT}/") {
        return Ok((VIRTUAL_ROOT.to_string(), Vec::new()));
    }
    let Some(relative) = input.strip_prefix(&format!("{VIRTUAL_ROOT}/")) else {
        return Err("path");
    };
    if relative.is_empty() || input.contains('\\') || input.chars().any(char::is_control) {
        return Err("path");
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
        return Err("path");
    }
    if segments
        .first()
        .is_some_and(|segment| is_reserved_top_level_entry(segment))
    {
        return Err("reserved");
    }
    Ok((format!("{VIRTUAL_ROOT}/{relative}"), segments))
}

fn validate_cursor(input: &str) -> Result<&str, &'static str> {
    if input.is_empty()
        || input.len() > 255
        || input.contains('/')
        || input.contains('\\')
        || input.chars().any(char::is_control)
    {
        return Err("cursor");
    }
    Ok(input)
}

fn readable_mime_type(path: &FsPath) -> Result<&'static str, &'static str> {
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
        Err("mime")
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
