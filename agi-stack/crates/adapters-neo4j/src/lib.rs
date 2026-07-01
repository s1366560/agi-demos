//! Server-only Neo4j adapter for the [`GraphStore`] port — the **production
//! knowledge-graph tier** of the Python -> Rust strangler migration
//! (`10-production-migration.md` §6.3 / F8).
//!
//! It speaks Bolt to the **same Neo4j the Python backend uses**
//! (`src/infrastructure/graph/`): `:Entity` nodes keyed by `uuid`, directed
//! relationships whose type defaults to `MENTIONS`. Because reads and writes hit
//! the shared graph, the strangler can flip `/graph/*` traffic from Python to
//! Rust with **zero data migration** — exactly the shared-DB pattern already used
//! for Postgres (`agistack-adapters-postgres`).
//!
//! This is the **third adapter behind the one [`GraphStore`] port**:
//! - `agistack_adapters_mem::InMemoryGraphStore` — browser/test tier (wasm-clean)
//! - `agistack_adapters_device::SqliteGraphStore` — on-device durable tier
//! - [`Neo4jGraphStore`] (here) — server production tier
//!
//! Its [`subgraph`](Neo4jGraphStore::subgraph) fetches the project slice over
//! Bolt and then runs the **same depth-bounded BFS** the other two tiers run
//! (duplicated locally to keep crate deps clean, exactly like the device
//! adapter), so structural graph results match across all three tiers. Ranking is
//! *not* here — that stays the deterministic pure math in `agistack_core::graph`.
//!
//! `neo4rs` drags in tokio + a Bolt/TLS stack, so — like every heavy adapter —
//! this crate is kept **out of the core/wasm path** (ADR-0001). Nothing here ever
//! appears in a port signature; the core only sees `dyn GraphStore`.

mod graph;

pub use graph::Neo4jGraphStore;

pub use neo4rs::{Error as Neo4jError, Graph};

/// Connect to Neo4j over Bolt. Thin wrapper over [`neo4rs::Graph::new`] so callers
/// (the server wiring, integration tests) get a stable entry point. The URI is the
/// Bolt endpoint, e.g. `neo4j://localhost:7687` or `bolt://localhost:7687`.
pub async fn connect(uri: &str, user: &str, password: &str) -> Result<Graph, neo4rs::Error> {
    Graph::new(uri, user, password).await
}
