//! Hexagonal ports — the **entire** contract between the portable core and the
//! outside world. Every side effect (storage, LLM, embeddings, vectors, time,
//! tool execution, checkpointing, change capture) is a trait here; each platform
//! supplies its own adapter. This is the Rust re-expression of the Python
//! `src/domain/ports/` boundary.
//!
//! Async is via `async-trait`; the executor is chosen by the host (tokio on the
//! server, `wasm-bindgen-futures` in the browser, `block_on` across FFI). No
//! port names a concrete runtime.

use async_trait::async_trait;

use crate::agent::types::{AgentAction, SessionState, TranscriptEntry};
use crate::model::{Entity, Episode, GraphEntity, Memory, Relationship, Subgraph};

/// Errors surfaced across core ports.
#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("not found")]
    NotFound,
    #[error("llm error: {0}")]
    Llm(String),
    #[error("embedding error: {0}")]
    Embedding(String),
    #[error("storage error: {0}")]
    Storage(String),
    #[error("tool error: {0}")]
    Tool(String),
    #[error("vector index error: {0}")]
    Vector(String),
    #[error("graph store error: {0}")]
    Graph(String),
    #[error("checkpoint error: {0}")]
    Checkpoint(String),
    #[error("plan error: {0}")]
    Plan(String),
    #[error("harness error: {0}")]
    Harness(String),
}

pub type CoreResult<T> = Result<T, CoreError>;

/// Platform-agnostic clock. Keeping `std::time` out of the core is what lets the
/// same code compile to `wasm32-unknown-unknown`, where `SystemTime` panics.
pub trait Clock: Send + Sync {
    fn now_ms(&self) -> i64;
}

/// Draft produced by a single LLM "extract" step before it becomes a [`Memory`].
#[derive(Debug, Clone)]
pub struct MemoryDraft {
    pub title: String,
    pub content: String,
    pub tags: Vec<String>,
    pub entities: Vec<Entity>,
}

/// The model port: both the memory-extraction skill and the agent "Think" step.
///
/// Folding both into one port mirrors the Python `infrastructure/llm` client,
/// which serves extraction and agent reasoning from the same provider.
#[async_trait]
pub trait LlmPort: Send + Sync {
    /// Turn an episode into a structured memory draft.
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft>;

    /// Decide the next ReAct action given the goal, the current round, the
    /// transcript so far, and the names of the available tools.
    ///
    /// Agent First: this is the one place a *semantic* decision is made; the
    /// engine only executes the structured [`AgentAction`] returned here.
    async fn decide(
        &self,
        goal: &str,
        round: u64,
        transcript: &[TranscriptEntry],
        available_tools: &[String],
    ) -> CoreResult<AgentAction>;
}

/// Text → dense vector.
#[async_trait]
pub trait EmbeddingPort: Send + Sync {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>>;
}

/// A vector id paired with its similarity score (cosine, higher = closer).
#[derive(Debug, Clone, PartialEq)]
pub struct ScoredId {
    pub id: String,
    pub score: f32,
}

/// Approximate-nearest-neighbour index. On the server this is pgvector; on
/// device it is sqlite-vec or a brute-force scan; in the browser an in-memory
/// HNSW. The port hides which (`01-portable-core.md` §3).
#[async_trait]
pub trait VectorIndexPort: Send + Sync {
    /// Insert or replace the vector for `id` within `project_id` scope.
    async fn upsert(&self, project_id: &str, id: &str, vector: &[f32]) -> CoreResult<()>;

    /// Return up to `k` nearest ids to `vector`, scoped to `project_id`.
    async fn query(&self, project_id: &str, vector: &[f32], k: usize) -> CoreResult<Vec<ScoredId>>;

    /// Remove a vector (no-op if absent).
    async fn remove(&self, project_id: &str, id: &str) -> CoreResult<()>;
}

/// Hexagonal port for **executing tools** — both trusted built-ins and sandboxed
/// third-party/MCP capabilities. The agent loop only sees this surface; whether a
/// call lands on a native `dyn Trait` or a WASM sandbox is the host's concern
/// (the trust axis, ADR-0002). `agistack-plugin-host` implements this over its
/// hot-pluggable registry.
#[async_trait]
pub trait ToolHost: Send + Sync {
    /// The tool names currently dispatchable.
    fn list_tools(&self) -> Vec<String>;
    /// Invoke a tool with a JSON input, returning a JSON output.
    async fn call(&self, tool: &str, input_json: &str) -> CoreResult<String>;
}

/// Persistence for agent [`SessionState`] — the checkpoint store behind crash
/// recovery (ADR-0005). In-memory for tests/browser, SQLite on device, Postgres
/// on the server: all behind this one port.
#[async_trait]
pub trait CheckpointStore: Send + Sync {
    /// Persist the latest state (insert-or-replace by `session_id`).
    async fn save(&self, state: &SessionState) -> CoreResult<()>;
    /// Load a session's last checkpoint, if any.
    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>>;
    /// Drop a session's checkpoint (no-op if absent).
    async fn delete(&self, session_id: &str) -> CoreResult<()>;
}

/// One captured change to local state — the unit the sync layer ships (Phase 4,
/// `01-portable-core.md` §5 / `08-control-data-plane-separation.md` §7). Recording
/// changes here is the data-plane seam that local-first sync reconciles later.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ChangeEvent {
    pub entity: String,
    pub entity_id: String,
    pub op: String,
    pub version: u32,
    pub at_ms: i64,
}

/// Out-port that captures local mutations for the (future) local-first sync
/// layer. Provided as a stable seam now so adapters can start emitting changes
/// before the CRDT/delta-sync engine lands.
#[async_trait]
pub trait ChangeLog: Send + Sync {
    async fn record(&self, event: ChangeEvent) -> CoreResult<()>;
}

/// Mirrors `MemoryRepository` in
/// `src/domain/ports/repositories/memory_repository.py` — including the default
/// `search_by_project` fallback.
#[async_trait]
pub trait MemoryRepository: Send + Sync {
    async fn save(&self, memory: Memory) -> CoreResult<Memory>;
    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>>;
    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>>;

    /// Default in-core search mirroring the Python fallback: case-insensitive
    /// substring over title/content. Concrete adapters override this to push
    /// search into storage (e.g. sqlite-vec / pgvector).
    async fn search_by_project(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<Memory>> {
        let needle = query.to_lowercase();
        let all = self.list_by_project(project_id, limit, 0).await?;
        Ok(all
            .into_iter()
            .filter(|m| {
                m.title.to_lowercase().contains(&needle)
                    || m.content.to_lowercase().contains(&needle)
            })
            .collect())
    }

    /// Count memories in a project, optionally filtered by the same
    /// case-insensitive title/content search as [`search_by_project`]. Default
    /// impl counts via the search/list fallback; storage-backed adapters override
    /// it with a `SELECT count(*)`.
    ///
    /// [`search_by_project`]: MemoryRepository::search_by_project
    async fn count_by_project(&self, project_id: &str, search: Option<&str>) -> CoreResult<usize> {
        let rows = match search {
            Some(q) => self.search_by_project(project_id, q, usize::MAX).await?,
            None => self.list_by_project(project_id, usize::MAX, 0).await?,
        };
        Ok(rows.len())
    }

    async fn delete(&self, id: &str) -> CoreResult<bool>;
}

/// Knowledge-graph storage — the local-first analogue of the Python Neo4j layer
/// (`src/infrastructure/graph/`). The server adapter is Neo4j (`neo4rs`, future
/// F8); the device adapter is SQLite relational tables traversed in-memory with
/// `petgraph` (decision 4, `10-production-migration.md` §6.3); an in-memory
/// adapter backs tests and the browser. All three sit behind this one port so the
/// portable core never learns which is underneath.
///
/// Multi-tenancy is a hard invariant: every method is `project_id`-scoped, exactly
/// like the Python graph queries filter on `project_id`/`tenant_id`. Ranking of
/// results is *not* here — that is the deterministic pure math in
/// [`crate::graph`], shared by every adapter so scores match byte-for-byte.
#[async_trait]
pub trait GraphStore: Send + Sync {
    /// Insert or replace an entity node (by `uuid`, within its `project_id`).
    async fn upsert_entity(&self, entity: GraphEntity) -> CoreResult<()>;

    /// Insert or replace a relationship edge (by `uuid`). Endpoints are entity
    /// `uuid`s; adapters need not enforce referential integrity (mirrors Neo4j
    /// MERGE semantics where edges may precede nodes during extraction).
    async fn upsert_relationship(&self, rel: Relationship) -> CoreResult<()>;

    /// Fetch one entity by `uuid`, scoped to `project_id`.
    async fn get_entity(&self, project_id: &str, uuid: &str) -> CoreResult<Option<GraphEntity>>;

    /// Direct (1-hop) neighbours reachable via **outgoing** relationships from
    /// `uuid`, scoped to `project_id`.
    async fn neighbors(&self, project_id: &str, uuid: &str) -> CoreResult<Vec<GraphEntity>>;

    /// Breadth-first `max_depth`-hop [`Subgraph`] rooted at `uuid` (the seed is
    /// included at depth 0), following outgoing relationships, scoped to
    /// `project_id`. `max_depth == 0` returns just the seed with no edges.
    async fn subgraph(
        &self,
        project_id: &str,
        uuid: &str,
        max_depth: usize,
    ) -> CoreResult<Subgraph>;

    /// Case-insensitive substring search over entity `name`/`summary` — the
    /// keyword tier of hybrid search and the always-correct baseline (the graph
    /// analogue of [`MemoryRepository::search_by_project`]). Returns up to `limit`
    /// entities; ordering is adapter-defined but stable.
    async fn search_entities(
        &self,
        project_id: &str,
        query: &str,
        limit: usize,
    ) -> CoreResult<Vec<GraphEntity>>;
}
