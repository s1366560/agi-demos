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
use crate::model::{
    Entity, Episode, GraphEntity, GraphExport, GraphStats, GraphStatsScope, Memory, Relationship,
    Subgraph,
};

/// Errors surfaced across core ports.
#[derive(Debug, thiserror::Error)]
pub enum CoreError {
    #[error("not found")]
    NotFound,
    #[error("llm error: {0}")]
    Llm(String),
    #[error("embedding error: {0}")]
    Embedding(String),
    #[error("rerank error: {0}")]
    Rerank(String),
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
    #[error("event stream error: {0}")]
    Event(String),
    #[error("container runtime error: {0}")]
    Container(String),
    #[error("email error: {0}")]
    Email(String),
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

/// Structured relationship candidate produced by an LLM extraction pass.
///
/// `source` and `target` intentionally name already-extracted entities instead
/// of graph UUIDs. The server graph projection layer resolves those names to
/// project-scoped graph nodes after access and tenancy have already been
/// established.
#[derive(Debug, Clone, PartialEq)]
pub struct RelationshipDraft {
    pub source: String,
    pub target: String,
    pub relation_type: String,
    pub fact: String,
    pub score: f32,
}

/// The model port: both the memory-extraction skill and the agent "Think" step.
///
/// Folding both into one port mirrors the Python `infrastructure/llm` client,
/// which serves extraction and agent reasoning from the same provider.
#[async_trait]
pub trait LlmPort: Send + Sync {
    /// Turn an episode into a structured memory draft.
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft>;

    /// Extract semantic relationships between already-extracted memory entities.
    ///
    /// The default is intentionally empty so existing local/device/browser LLM
    /// stand-ins remain compatible and production hosts can gate this optional
    /// graph-enrichment pass independently of memory ingestion.
    async fn extract_relationships(&self, _memory: &Memory) -> CoreResult<Vec<RelationshipDraft>> {
        Ok(Vec::new())
    }

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

/// A reranked candidate: its original index paired with a relevance score
/// (higher = more relevant). Cross-encoder rerankers jointly score each
/// query↔document pair, so this ordering is sharper than the bi-encoder cosine
/// that [`EmbeddingPort`] + [`VectorIndexPort`] produce — it is the second stage
/// of the Python backend's hybrid search.
#[derive(Debug, Clone, PartialEq)]
pub struct RerankHit {
    pub index: usize,
    pub score: f32,
}

/// Query + candidate documents → documents reordered by cross-encoder relevance.
///
/// Mirrors the Python `hybrid_search` reranking stage (a BGE reranker over
/// pgvector/graph candidates). On the server this is an HTTP reranker
/// (BGE/Cohere/Jina-compatible); on device a local cross-encoder or a pass-through.
/// Scores are provider-raw (e.g. logits) — compare **within** one response,
/// don't assume a `[0,1]` range.
#[async_trait]
pub trait RerankPort: Send + Sync {
    /// Score each of `documents` against `query`, returning hits sorted by
    /// descending relevance (most relevant first).
    async fn rerank(&self, query: &str, documents: &[String]) -> CoreResult<Vec<RerankHit>>;
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

/// One entry in an event stream: the adapter-assigned monotonic `id` used for
/// incremental reads, plus the already-serialized event `payload`. Mirrors a
/// Redis Streams entry (a stream id + a field map). Keeping the payload opaque
/// (serialized JSON) is deliberate — the core stays decoupled from any concrete
/// event enum, and every adapter (Redis / in-memory) stores the identical bytes,
/// so payload sequences match across tiers even though the `id` formats differ.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct StreamEntry {
    pub id: String,
    pub payload: String,
}

/// Append-and-read event bus keyed by an opaque `topic` (e.g.
/// `agent:events:{conversation_id}`). The Rust re-expression of the Python
/// **Redis Streams agent-event bus** (F5, `10-production-migration.md` §3): the
/// SessionProcessor appends domain events, the WebSocket bridge reads them
/// incrementally and forwards to the frontend. This is the data-plane seam that
/// decouples event production from delivery.
///
/// The server adapter is Redis Streams (`redis`, `XADD`/`XRANGE`, server-only);
/// an in-memory adapter backs tests and the browser. Both sit behind this one
/// port, so the portable core never learns which is underneath. `max_len` bounds
/// retained history (Redis `XADD MAXLEN`), giving the same trim/backpressure
/// behaviour as the Python `maxlen=1000` stream.
///
/// Because entry ids are adapter-specific opaque strings, callers must echo back
/// the last id they saw for incremental reads (exactly like a Redis Streams
/// consumer); they must not parse or compare ids across adapters.
#[async_trait]
pub trait EventStream: Send + Sync {
    /// Append `payload` to `topic`, trimming the stream to at most `max_len`
    /// most-recent entries (`0` = unbounded). Returns the new entry's id.
    async fn append(&self, topic: &str, payload: &str, max_len: usize) -> CoreResult<String>;

    /// Append several payloads to `topic` in order, returning the assigned
    /// ids. The default loops [`append`](Self::append); adapters over network
    /// storage override it with a single pipelined round-trip (the workspace
    /// mention path appends up to 128 token-chunk events per response).
    async fn append_batch(
        &self,
        topic: &str,
        payloads: &[String],
        max_len: usize,
    ) -> CoreResult<Vec<String>> {
        let mut ids = Vec::with_capacity(payloads.len());
        for payload in payloads {
            ids.push(self.append(topic, payload, max_len).await?);
        }
        Ok(ids)
    }

    /// Read up to `limit` entries from `topic` strictly after `after_id`
    /// (empty string or `"0"` = from the beginning), in append order.
    async fn read_after(
        &self,
        topic: &str,
        after_id: &str,
        limit: usize,
    ) -> CoreResult<Vec<StreamEntry>>;
}

/// Metadata about a stored object (a blob's `size` in bytes and optional MIME
/// `content_type`), returned by [`ObjectStore::stat`]. Mirrors the subset of an
/// S3 `HeadObject` response the artifact/attachment paths actually read.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ObjectMeta {
    pub size: u64,
    pub content_type: Option<String>,
}

/// Blob storage keyed by an opaque string `key` (e.g.
/// `artifacts/{project}/{id}`). The Rust re-expression of the Python
/// **object-storage** path (F6, `10-production-migration.md` §3) behind
/// artifacts / attachments / instance-files: opaque bytes in, opaque bytes out,
/// listed by key prefix.
///
/// The server adapter is S3/MinIO (`aws-sdk-s3`, server-only); an in-memory
/// adapter backs tests and the browser/device tier. Both sit behind this one
/// port, so the portable core never learns which is underneath. Keeping the
/// value a raw byte vector (plus optional `content_type`) keeps the core
/// decoupled from any concrete artifact schema — every adapter stores the
/// identical bytes, so contents match across tiers.
///
/// `get`/`stat` return `None` for a missing key (never an error), mirroring the
/// Python "404 on absent object" behaviour and making cross-adapter parity a
/// simple `Option` compare. An object stored without a `content_type` reports
/// S3/MinIO's canonical default `application/octet-stream` on `stat` (both tiers
/// normalize to it), so the metadata never diverges by adapter.
#[async_trait]
pub trait ObjectStore: Send + Sync {
    /// Store `bytes` under `key` (overwriting any existing object), tagging it
    /// with an optional MIME `content_type` (S3 `Content-Type`).
    async fn put(&self, key: &str, bytes: Vec<u8>, content_type: Option<&str>) -> CoreResult<()>;

    /// Fetch the bytes stored under `key`, or `None` if the key is absent.
    async fn get(&self, key: &str) -> CoreResult<Option<Vec<u8>>>;

    /// Return metadata for `key` without transferring the body, or `None` if the
    /// key is absent.
    async fn stat(&self, key: &str) -> CoreResult<Option<ObjectMeta>>;

    /// Delete `key`. Deleting an absent key is a no-op success (S3 semantics).
    async fn delete(&self, key: &str) -> CoreResult<()>;

    /// List all keys beginning with `prefix` (empty = all), sorted ascending for
    /// deterministic, cross-adapter-comparable results.
    async fn list(&self, prefix: &str) -> CoreResult<Vec<String>>;
}

/// Desired configuration for a sandbox container, the input to
/// [`ContainerRuntime::create`]. A minimal, runtime-neutral subset of the Python
/// `MCPSandboxAdapter` container spec: the `image` to run, an optional `cmd`
/// override, `env` pairs, `labels` used to tag ownership (e.g. `project_id`) so
/// a fleet can be reconciled/listed by selector, and optional TCP port bindings
/// for sandbox services (MCP, noVNC, ttyd). It deliberately stores plain port
/// numbers, not Docker/bollard types.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContainerSpec {
    pub image: String,
    pub cmd: Option<Vec<String>>,
    pub env: Vec<(String, String)>,
    pub labels: Vec<(String, String)>,
    pub ports: Vec<PortBinding>,
}

/// Runtime-neutral TCP port binding for a sandbox container. `container_port` is
/// the port inside the container; `host_port` is the selected host port. A
/// `host_port` of `0` asks runtimes that support it to auto-assign a free port.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PortBinding {
    pub container_port: u16,
    pub host_port: u16,
    pub host_ip: Option<String>,
}

/// Normalized lifecycle state of a container, collapsing the various
/// runtime-specific state strings into the handful the sandbox layer reacts to.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ContainerState {
    /// Created but not yet started.
    Created,
    /// Currently running.
    Running,
    /// Ran and exited (see [`ContainerStatus::exit_code`]).
    Exited,
    /// Any other/unknown runtime state.
    Unknown,
}

/// Observed status of a container, returned by [`ContainerRuntime::status`].
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ContainerStatus {
    pub id: String,
    pub state: ContainerState,
    pub running: bool,
    pub exit_code: Option<i64>,
    pub ports: Vec<PortBinding>,
}

/// Hexagonal port for **provisioning sandbox containers** — the lifecycle layer
/// *beneath* [`ToolHost`]: it creates/starts/stops the isolated environment that
/// a remote [`ToolHost`] (e.g. the MCP-over-WebSocket adapter) then talks to.
/// This is the Rust re-expression of the Python `MCPSandboxAdapter` container
/// lifecycle (F9, `10-production-migration.md` §3): create → start → health →
/// stop.
///
/// The server adapter drives a real Docker daemon (`bollard`, server-only); an
/// in-memory adapter models the identical lifecycle state machine for offline
/// tests and as a device/test double. Both sit behind this one port, so the
/// portable core never learns whether a real container or a fake is underneath.
///
/// Because a container runtime is a *protocol/lifecycle* surface (not opaque
/// data storage), cross-adapter equivalence is **state-machine conformance**
/// (create→Created, start→Running, stop→Exited, remove→absent), not byte
/// parity: the live Docker daemon and the in-memory fake transition through the
/// same [`ContainerState`] sequence.
#[async_trait]
pub trait ContainerRuntime: Send + Sync {
    /// Create a container from `spec` without starting it, returning its id.
    async fn create(&self, spec: &ContainerSpec) -> CoreResult<String>;

    /// Start a previously created container.
    async fn start(&self, id: &str) -> CoreResult<()>;

    /// Inspect `id`, or `None` if no such container exists (e.g. after remove).
    async fn status(&self, id: &str) -> CoreResult<Option<ContainerStatus>>;

    /// Stop a running container (no-op if already stopped).
    async fn stop(&self, id: &str) -> CoreResult<()>;

    /// Remove `id`. Removing an absent container is a no-op success.
    async fn remove(&self, id: &str) -> CoreResult<()>;

    /// List ids of containers matching an optional `(label_key, label_value)`
    /// selector (`None` = all managed containers), sorted ascending.
    async fn list(&self, label: Option<(&str, &str)>) -> CoreResult<Vec<String>>;
}

/// A transactional email to send, mirroring the fields the Python invitation /
/// notification flow fills in (`src/.../notifications`, `smtp_config`). A minimal
/// runtime-neutral subset: a single `from`, one-or-more `to`, a `subject`, and a
/// plain-text body with an optional HTML alternative. Addresses are validated by
/// the adapter (the port stays dependency-free `String`s so it compiles to
/// `wasm32`).
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct EmailMessage {
    /// RFC 5322 sender address (e.g. `"MemStack <no-reply@memstack.ai>"` or a
    /// bare `"no-reply@memstack.ai"`).
    pub from: String,
    /// One or more recipient addresses.
    pub to: Vec<String>,
    /// Subject line.
    pub subject: String,
    /// Plain-text body (always present — the lowest-common-denominator part).
    pub body_text: String,
    /// Optional HTML alternative; when set the adapter sends a `multipart/alternative`.
    pub body_html: Option<String>,
}

/// Outbound transactional email — the Rust re-expression of the Python SMTP path
/// (invitation emails, notifications). This is **F10** of the strangler
/// migration (`10-production-migration.md` §3): the mail-sending capability P2
/// (invitations) and P7-G4 (notifications) depend on.
///
/// Like [`ObjectStore`]/[`ContainerRuntime`], the port is runtime-agnostic (plain
/// `EmailMessage` + `async_trait`, no SMTP/network types leak in) so the core
/// stays wasm-compilable (ADR-0001); the heavy `lettre` SMTP client lives only in
/// the server-only adapter. Because email delivery is an I/O side effect (not a
/// value store), cross-adapter equivalence is **behavioural** (the in-memory fake
/// records exactly what a real SMTP send would transmit), not byte parity.
#[async_trait]
pub trait EmailSender: Send + Sync {
    /// Send `message`. Returns `Ok(())` once the MTA has accepted it (a real SMTP
    /// `250`), or [`CoreError::Email`] on a rejected envelope / transport failure.
    async fn send(&self, message: &EmailMessage) -> CoreResult<()>;
}

/// Mirrors `MemoryRepository` in
/// `src/domain/ports/repositories/memory_repository.py` — including the default
/// `search_by_project` fallback.
#[async_trait]
pub trait MemoryRepository: Send + Sync {
    async fn save(&self, memory: Memory) -> CoreResult<Memory>;
    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>>;

    /// Batch fetch by ids — backs semantic-search hydration, which needs k rows
    /// per query. Returned order is **unspecified**: callers that need a
    /// specific order (e.g. vector rank) must reorder themselves. The default
    /// loops [`find_by_id`](Self::find_by_id); adapters over network storage
    /// override it with a single round-trip (`WHERE id = ANY(...)`).
    async fn find_by_ids(&self, ids: &[String]) -> CoreResult<Vec<Memory>> {
        let mut out = Vec::with_capacity(ids.len());
        for id in ids {
            if let Some(memory) = self.find_by_id(id).await? {
                out.push(memory);
            }
        }
        Ok(out)
    }

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

    /// Delete an entity by `uuid`, scoped to `project_id`, and remove any
    /// project-scoped relationships that touch it so graph snapshots never return
    /// dangling edges.
    async fn delete_entity(&self, project_id: &str, uuid: &str) -> CoreResult<()>;

    /// Delete one relationship by `uuid`, scoped to `project_id`.
    async fn delete_relationship(&self, project_id: &str, uuid: &str) -> CoreResult<()>;

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

    /// Full project-scoped slice — every [`GraphEntity`] in the project plus the
    /// [`Relationship`]s whose *both* endpoints exist in it — loaded in one pass
    /// for server-side multi-seed traversals that would otherwise issue one
    /// [`subgraph`](GraphStore::subgraph) round-trip per seed. `project_id`-scoped
    /// like every other method (multi-tenancy invariant).
    async fn project_slice(
        &self,
        project_id: &str,
    ) -> CoreResult<(Vec<GraphEntity>, Vec<Relationship>)>;

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

    /// Aggregate node/relationship counts for data-export stats. `All` mirrors
    /// Python's admin-wide scope; `Projects([])` is intentionally empty.
    async fn stats(&self, scope: GraphStatsScope) -> CoreResult<GraphStats>;

    /// Export raw graph entities and relationships for the data-export surface.
    /// The HTTP layer decides which entity types become episodes, entities, or
    /// communities to preserve Python's route-specific envelope.
    async fn export(&self, scope: GraphStatsScope) -> CoreResult<GraphExport>;

    /// Count `Episodic` graph nodes older than `cutoff_ms` for cleanup dry-runs.
    async fn count_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff_ms: i64,
    ) -> CoreResult<usize>;

    /// Delete `Episodic` graph nodes older than `cutoff_ms`, removing dangling
    /// relationships as part of the adapter's graph-delete semantics.
    async fn delete_episodes_older_than(
        &self,
        scope: GraphStatsScope,
        cutoff_ms: i64,
    ) -> CoreResult<usize>;
}
