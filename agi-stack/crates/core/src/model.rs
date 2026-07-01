//! Domain model — the platform-agnostic entities.
//!
//! Mirrors the pure domain layer of the Python backend
//! (`src/domain/model/memory/…`, `src/domain/model/project/…`). Timestamps are
//! epoch millis (`i64`) so nothing here depends on `std::time`, keeping the type
//! layer compilable on `wasm32-unknown-unknown`.

use serde::{Deserialize, Serialize};

/// Mirrors `SourceType` in `src/domain/model/memory/episode.py`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum SourceType {
    Text,
    Json,
    Document,
    Api,
    Conversation,
}

/// A lightweight entity reference extracted from content (the knowledge-graph
/// seed). On the server these become Neo4j nodes; on device they live in SQLite
/// relational tables (`01-portable-core.md` §3).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Entity {
    pub name: String,
    pub kind: String,
}

/// A knowledge-graph entity **node** — the richer, uniquely-identified form used
/// by the graph store (as opposed to the lightweight [`Entity`] reference carried
/// inside a [`Memory`]). Mirrors the Neo4j `Entity` label in
/// `src/infrastructure/graph/` (name / entity_type / summary / uuid / project_id
/// / tenant_id / name_embedding).
///
/// On the server these are Neo4j nodes; on device they are rows in a SQLite
/// relational table traversed in-memory with `petgraph` (decision 4,
/// `10-production-migration.md` §6.3). The [`crate::ports::GraphStore`] port hides
/// which — the portable core never notices. Every field that scopes access
/// (`project_id` / `tenant_id`) is carried so the store can enforce multi-tenancy.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct GraphEntity {
    pub uuid: String,
    pub name: String,
    pub entity_type: String,
    #[serde(default)]
    pub summary: String,
    pub project_id: String,
    #[serde(default)]
    pub tenant_id: Option<String>,
    pub created_at_ms: i64,
    /// Optional dense embedding of `name` (+ `summary`), used by the vector tier
    /// of hybrid search. Kept `Option` because keyword-only device builds skip it.
    #[serde(default)]
    pub name_embedding: Option<Vec<f32>>,
}

/// A directed relationship between two [`GraphEntity`] nodes, carrying the
/// extracted `fact` and a confidence `score`. Mirrors the Neo4j `MENTIONS` edge
/// (`fact` / `score`). `relation_type` defaults to `"MENTIONS"` to match the
/// Python extractor's dominant edge.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Relationship {
    pub uuid: String,
    pub source_uuid: String,
    pub target_uuid: String,
    #[serde(default = "default_relation_type")]
    pub relation_type: String,
    #[serde(default)]
    pub fact: String,
    pub score: f32,
    pub project_id: String,
    pub created_at_ms: i64,
}

fn default_relation_type() -> String {
    "MENTIONS".to_string()
}

/// A connected slice of the knowledge graph — the entities reachable from a seed
/// within a hop budget, plus the relationships that connect them. Returned by
/// [`crate::ports::GraphStore::subgraph`]; the local-first analogue of a Neo4j
/// `MATCH path` result.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct Subgraph {
    pub entities: Vec<GraphEntity>,
    pub relationships: Vec<Relationship>,
}

/// A discrete interaction to be distilled into memory. Mirrors `Episode` in
/// `src/domain/model/memory/episode.py`.
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

/// Semantic memory extracted from an episode. Mirrors `Memory` in
/// `src/domain/model/memory/memory.py`.
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

/// Multi-tenant isolation unit. Every query is scoped by `project_id`; on the
/// server this is the boundary of an independent knowledge graph, on device it
/// is the local workspace. Mirrors `Project` in `src/domain/model/project/`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Project {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub tenant_id: Option<String>,
    pub created_at_ms: i64,
}
