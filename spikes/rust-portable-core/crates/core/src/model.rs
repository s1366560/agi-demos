use serde::{Deserialize, Serialize};

/// Mirrors `SourceType` in src/domain/model/memory/episode.py
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Text,
    Json,
    Document,
    Api,
    Conversation,
}

/// A lightweight entity reference extracted from content.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Entity {
    pub name: String,
    pub kind: String,
}

/// Mirrors `Episode` in src/domain/model/memory/episode.py.
/// Timestamps are epoch millis (i64) so the type is platform-agnostic.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Episode {
    pub content: String,
    pub source_type: SourceType,
    pub valid_at_ms: i64,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub project_id: Option<String>,
    #[serde(default)]
    pub user_id: Option<String>,
}

/// Mirrors `Memory` in src/domain/model/memory/memory.py.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Memory {
    pub id: String,
    pub project_id: String,
    pub title: String,
    pub content: String,
    pub author_id: String,
    pub content_type: String,
    pub tags: Vec<String>,
    pub entities: Vec<Entity>,
    pub version: u32,
    pub status: String,
    pub created_at_ms: i64,
    #[serde(default)]
    pub embedding: Option<Vec<f32>>,
}
