//! UniFFI binding — the **mobile native-package** path.
//!
//! This wraps the *same* portable [`MemoryService`] used by the server and the
//! WASM build, backed here by the embedded-SQLite adapter (the on-device store).
//! UniFFI generates idiomatic Swift (iOS) and Kotlin (Android) from these
//! annotations — no hand-written glue.
//!
//! The exported surface is intentionally **synchronous**: it `block_on`s the
//! runtime-agnostic core futures (same trick as the unit tests). A production
//! binding would export async and bridge to the foreign executor; for a spike
//! this keeps the FFI surface trivial while still exercising the real core.

use std::sync::Arc;

use memstack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use memstack_adapters_sqlite::SqliteMemoryRepository;
use memstack_core::{Episode, MemoryService, SourceType};

uniffi::setup_scaffolding!();

#[derive(uniffi::Object)]
pub struct MobileCore {
    service: MemoryService,
}

#[uniffi::export]
impl MobileCore {
    /// Open (or create) an on-device memory store at `db_path`.
    #[uniffi::constructor]
    pub fn new(db_path: String) -> Arc<Self> {
        let repo = Arc::new(
            SqliteMemoryRepository::open(&db_path).expect("failed to open sqlite store"),
        );
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(8)),
            Arc::new(SystemClock),
        );
        Arc::new(Self { service })
    }

    /// Ingest an episode and return the created Memory as JSON.
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

    /// Search memories in a project; returns a JSON array.
    pub fn search(&self, project_id: String, query: String, limit: u32) -> String {
        let hits = futures::executor::block_on(self.service.search(
            &project_id,
            &query,
            limit as usize,
        ))
        .expect("search failed");
        serde_json::to_string(&hits).expect("serialize hits")
    }
}
