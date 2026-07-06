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

use std::{fmt, sync::Arc};

use agistack_adapters_device::{SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use agistack_core::{Episode, MemoryService, SourceType};

uniffi::setup_scaffolding!();

#[derive(Debug, uniffi::Error)]
pub enum MobileCoreError {
    Operation { message: String },
}

impl MobileCoreError {
    fn operation(message: impl Into<String>) -> Self {
        Self::Operation {
            message: message.into(),
        }
    }
}

impl fmt::Display for MobileCoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Operation { message } => f.write_str(message),
        }
    }
}

impl std::error::Error for MobileCoreError {}

type MobileCoreResult<T> = Result<T, MobileCoreError>;

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
    pub fn new(db_path: String) -> MobileCoreResult<Arc<Self>> {
        let repo = Arc::new(SqliteMemoryRepository::open(&db_path).map_err(|err| {
            MobileCoreError::operation(format!("failed to open sqlite memory store: {err}"))
        })?);
        let vectors = Arc::new(SqliteVectorIndex::open(&format!("{db_path}.vec")).map_err(
            |err| MobileCoreError::operation(format!("failed to open sqlite vector index: {err}")),
        )?);
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(64)),
            Arc::new(SystemClock),
        )
        .with_vectors(vectors);
        Ok(Arc::new(Self { service }))
    }

    /// Ingest an episode (extract → embed → persist → index) and return the
    /// created Memory as JSON.
    pub fn ingest(
        &self,
        project_id: String,
        author_id: String,
        content: String,
    ) -> MobileCoreResult<String> {
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
        .map_err(|err| MobileCoreError::operation(format!("failed to ingest memory: {err}")))?;
        serde_json::to_string(&mem)
            .map_err(|err| MobileCoreError::operation(format!("failed to serialize memory: {err}")))
    }

    /// Keyword search within a project; returns a JSON array of Memory.
    pub fn search(
        &self,
        project_id: String,
        query: String,
        limit: u32,
    ) -> MobileCoreResult<String> {
        let hits =
            futures::executor::block_on(self.service.search(&project_id, &query, limit as usize))
                .map_err(|err| MobileCoreError::operation(format!("failed to search: {err}")))?;
        serde_json::to_string(&hits)
            .map_err(|err| MobileCoreError::operation(format!("failed to serialize hits: {err}")))
    }

    /// Semantic (vector) search within a project; returns a JSON array of Memory.
    pub fn semantic_search(
        &self,
        project_id: String,
        query: String,
        limit: u32,
    ) -> MobileCoreResult<String> {
        let hits = futures::executor::block_on(self.service.semantic_search(
            &project_id,
            &query,
            limit as usize,
        ))
        .map_err(|err| {
            MobileCoreError::operation(format!("failed to run semantic search: {err}"))
        })?;
        serde_json::to_string(&hits)
            .map_err(|err| MobileCoreError::operation(format!("failed to serialize hits: {err}")))
    }
}

#[cfg(test)]
mod tests {
    use std::time::{SystemTime, UNIX_EPOCH};

    use super::*;

    fn temp_db_path(name: &str) -> String {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        std::env::temp_dir()
            .join(format!(
                "agistack-mobile-{name}-{}-{nonce}.db",
                std::process::id()
            ))
            .to_string_lossy()
            .into_owned()
    }

    fn remove_mobile_core_files(db_path: &str) {
        let _ = std::fs::remove_file(db_path);
        let _ = std::fs::remove_file(format!("{db_path}.vec"));
    }

    #[test]
    fn constructor_returns_error_for_unopenable_store_path() {
        let err = match MobileCore::new("/dev/null/store.db".to_string()) {
            Ok(_) => panic!("constructor should reject an unopenable sqlite path"),
            Err(err) => err,
        };

        assert!(matches!(err, MobileCoreError::Operation { .. }));
        assert!(err.to_string().starts_with("failed to open sqlite"));
    }

    #[test]
    fn mobile_core_round_trips_memory_json_without_panicking() {
        let db_path = temp_db_path("roundtrip");
        let core = MobileCore::new(db_path.clone()).unwrap();

        let memory_json = core
            .ingest(
                "p1".to_string(),
                "u1".to_string(),
                "local-first mobile memory".to_string(),
            )
            .unwrap();
        let memory: serde_json::Value = serde_json::from_str(&memory_json).unwrap();
        assert_eq!(memory["project_id"], "p1");

        let hits_json = core
            .search("p1".to_string(), "mobile".to_string(), 10)
            .unwrap();
        let hits: serde_json::Value = serde_json::from_str(&hits_json).unwrap();
        assert_eq!(hits.as_array().unwrap().len(), 1);

        drop(core);
        remove_mobile_core_files(&db_path);
    }
}
