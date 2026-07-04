use serde::Serialize;
use serde_json::{json, Value};

use agistack_core::model::Memory;

/// Format epoch-millis as an RFC 3339 / ISO-8601 UTC timestamp, matching how
/// pydantic serializes the Python `created_at` (`DateTime(timezone=True)`).
pub(super) fn rfc3339(ms: i64) -> String {
    chrono::DateTime::<chrono::Utc>::from_timestamp_millis(ms)
        .unwrap_or(chrono::DateTime::<chrono::Utc>::UNIX_EPOCH)
        .to_rfc3339_opts(chrono::SecondsFormat::Secs, true)
}

/// Byte-compatible with the Python `MemoryResponse`. Fields the portable core
/// does not model (`relationships`, `collaborators`, `is_public`,
/// `processing_status`, `metadata`, `updated_at`, `task_id`) are emitted with the
/// same defaults the Postgres adapter writes, so a Rust-served response is
/// indistinguishable from a Python-served one for these strangled routes.
#[derive(Serialize)]
pub(super) struct MemoryResponse {
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
pub(super) struct MemoryListResponse {
    pub(super) memories: Vec<MemoryResponse>,
    pub(super) total: usize,
    pub(super) page: usize,
    pub(super) page_size: usize,
}

#[derive(Serialize)]
pub(super) struct EpisodeResponse {
    pub(super) id: String,
    pub(super) name: String,
    pub(super) content: String,
    pub(super) status: String,
    pub(super) created_at: Option<String>,
    pub(super) message: Option<String>,
    pub(super) task_id: Option<String>,
    pub(super) workflow_id: Option<String>,
}

#[derive(Serialize)]
pub(super) struct ShortTermRecallResponse {
    pub(super) results: Vec<Value>,
    pub(super) total: usize,
    pub(super) window_minutes: i64,
}
