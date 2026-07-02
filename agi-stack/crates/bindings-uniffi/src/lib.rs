//! UniFFI binding — the **mobile native-package** path for agi-stack.
//!
//! Wraps the *same* portable [`MemoryService`] used by the server and the WASM
//! build, backed here by the embedded-SQLite device adapters (the on-device
//! store + vector index). UniFFI generates idiomatic Swift (iOS) and Kotlin
//! (Android) from these annotations — no hand-written glue. The resulting
//! `cdylib` is the Android `.so`; the `staticlib` is the iOS `.a`.
//!
//! The exported surface is intentionally **synchronous**: it `block_on`s the
//! runtime-agnostic core futures (the same trick the unit tests use), so the
//! binding inherits the no-tokio / no-`std::time` core invariant (ADR-0001).
//! A production binding would export async and bridge to the foreign executor;
//! for the device-artifact milestone this keeps the FFI surface trivial while
//! still exercising the real core end-to-end (SQLite persistence included).

use std::sync::Arc;

use agistack_adapters_device::{SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use agistack_core::{Episode, MemoryService, SourceType};

uniffi::setup_scaffolding!();

/// Handle to an on-device agi-stack core: an embedded SQLite memory store + a
/// SQLite vector index wired into the portable [`MemoryService`]. One value is
/// constructed per store and shared (`Arc`) across the foreign side.
#[derive(uniffi::Object)]
pub struct MobileCore {
    service: MemoryService,
}

#[uniffi::export]
impl MobileCore {
    /// Open (or create) an on-device store rooted at `db_path`. The vector index
    /// is kept alongside it at `{db_path}.vec`.
    #[uniffi::constructor]
    pub fn new(db_path: String) -> Arc<Self> {
        let repo = Arc::new(
            SqliteMemoryRepository::open(&db_path).expect("failed to open sqlite memory store"),
        );
        let vectors = Arc::new(
            SqliteVectorIndex::open(&format!("{db_path}.vec"))
                .expect("failed to open sqlite vector index"),
        );
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(64)),
            Arc::new(SystemClock),
        )
        .with_vectors(vectors);
        Arc::new(Self { service })
    }

    /// Ingest an episode (extract → embed → persist → index) and return the
    /// created Memory as JSON.
    pub fn ingest(&self, project_id: String, author_id: String, content: String) -> String {
        let episode = Episode {
            content,
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some(project_id.clone()),
            user_id: None,
        };
        let mem = futures::executor::block_on(self.service.ingest_episode(
            &project_id,
            &author_id,
            &episode,
        ))
        .expect("ingest failed");
        serde_json::to_string(&mem).expect("serialize memory")
    }

    /// Keyword search within a project; returns a JSON array of Memory.
    pub fn search(&self, project_id: String, query: String, limit: u32) -> String {
        let hits =
            futures::executor::block_on(self.service.search(&project_id, &query, limit as usize))
                .expect("search failed");
        serde_json::to_string(&hits).expect("serialize hits")
    }

    /// Semantic (vector) search within a project; returns a JSON array of Memory.
    pub fn semantic_search(&self, project_id: String, query: String, limit: u32) -> String {
        let hits = futures::executor::block_on(self.service.semantic_search(
            &project_id,
            &query,
            limit as usize,
        ))
        .expect("semantic search failed");
        serde_json::to_string(&hits).expect("serialize hits")
    }
}
