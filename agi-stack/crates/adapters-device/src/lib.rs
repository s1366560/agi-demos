//! `agistack-adapters-device`: **embedded SQLite adapters** — the on-device
//! (local-first) tier of agi-stack's hexagonal ports.
//!
//! Same ports as `agistack-adapters-mem`, but durable: data survives process
//! restarts, which is what makes on-device crash recovery and offline operation
//! real. Bundled SQLite compiles from source, so these cross-compile to iOS and
//! Android unchanged. On the server the same ports are backed by
//! Postgres/pgvector instead — the portable core never notices the difference
//! (`02-platform-adapters.md`).
//!
//! Provided adapters:
//!   - [`repo::SqliteMemoryRepository`]     — [`agistack_core::MemoryRepository`]
//!     (overrides `search_by_project` with a SQL `LIKE` push-down)
//!   - [`checkpoint::SqliteCheckpointStore`] — [`agistack_core::CheckpointStore`]
//!     (durable agent crash recovery, ADR-0005)
//!   - [`vector::SqliteVectorIndex`]        — [`agistack_core::VectorIndexPort`]
//!     (brute-force cosine today; sqlite-vec-backed in a production device build)

pub mod checkpoint;
pub mod repo;
pub mod vector;

pub use checkpoint::SqliteCheckpointStore;
pub use repo::SqliteMemoryRepository;
pub use vector::SqliteVectorIndex;
