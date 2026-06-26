//! Tauri desktop shell for agi-stack.
//!
//! This is the **PC** platform shell (03-platform-adapters §5): it links the
//! *same* portable [`agistack_core`] with the embedded **device** adapters
//! (`agistack-adapters-device`, SQLite) and exposes `ingest` / `search` /
//! `semantic_search` as Tauri commands to a minimal HTML frontend.
//!
//! Invariant: the core stays runtime-agnostic. Tokio lives only here in the
//! shell (Tauri's async command runtime); the core never names a runtime. The
//! command logic is factored into [`DesktopCore`] so it is unit-testable
//! **headlessly** — without launching a webview — which is exactly what the
//! `#[cfg(test)]` smoke test below does.

use std::sync::Arc;

use agistack_adapters_device::{SqliteMemoryRepository, SqliteVectorIndex};
use agistack_adapters_mem::{HashEmbedding, StubLlm, SystemClock};
use agistack_core::{Episode, MemoryService, SourceType};
use tauri::State;

/// Embedding width for the on-device hash embedding (toy; Wave F upgrades the
/// vector path to sqlite-vec + a real embedding).
const DIM: usize = 32;

/// The desktop core: the portable [`MemoryService`] wired to SQLite-backed
/// device adapters. Cheap to clone (`Arc`-backed), so commands clone it out of
/// Tauri state before awaiting.
#[derive(Clone)]
pub struct DesktopCore {
    service: MemoryService,
}

impl DesktopCore {
    /// Open (or create) the on-disk SQLite databases at `db_path`.
    pub fn open(db_path: &str) -> Result<Self, String> {
        let repo = Arc::new(SqliteMemoryRepository::open(db_path).map_err(err)?);
        let vectors = Arc::new(SqliteVectorIndex::open(db_path).map_err(err)?);
        Ok(Self::wire(repo, vectors))
    }

    /// In-memory wiring for tests / ephemeral runs.
    pub fn in_memory() -> Result<Self, String> {
        let repo = Arc::new(SqliteMemoryRepository::in_memory().map_err(err)?);
        let vectors = Arc::new(SqliteVectorIndex::in_memory().map_err(err)?);
        Ok(Self::wire(repo, vectors))
    }

    fn wire(repo: Arc<SqliteMemoryRepository>, vectors: Arc<SqliteVectorIndex>) -> Self {
        // SystemClock is the native wall clock (desktop is native, so no wasm
        // gating concern here); the wasm shell injects WasmClock instead.
        let service = MemoryService::new(
            repo,
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(DIM)),
            Arc::new(SystemClock),
        )
        .with_vectors(vectors);
        Self { service }
    }

    /// Ingest an episode; returns the created `Memory` as a JSON string.
    pub async fn ingest(
        &self,
        project_id: &str,
        author_id: &str,
        content: &str,
    ) -> Result<String, String> {
        let episode = Episode {
            content: content.to_string(),
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some(project_id.to_string()),
            user_id: None,
        };
        let memory = self
            .service
            .ingest_episode(project_id, author_id, &episode)
            .await
            .map_err(err)?;
        serde_json::to_string(&memory).map_err(err)
    }

    /// Keyword search; returns a JSON array of matching memories.
    pub async fn search(&self, project_id: &str, q: &str, limit: usize) -> Result<String, String> {
        let hits = self.service.search(project_id, q, limit).await.map_err(err)?;
        serde_json::to_string(&hits).map_err(err)
    }

    /// Vector/semantic search; returns a JSON array of matching memories.
    pub async fn semantic_search(
        &self,
        project_id: &str,
        q: &str,
        limit: usize,
    ) -> Result<String, String> {
        let hits = self
            .service
            .semantic_search(project_id, q, limit)
            .await
            .map_err(err)?;
        serde_json::to_string(&hits).map_err(err)
    }
}

fn err<E: std::fmt::Display>(e: E) -> String {
    e.to_string()
}

// --- Tauri commands: thin shells over DesktopCore. ---

#[tauri::command]
async fn ingest(
    core: State<'_, DesktopCore>,
    project_id: String,
    author_id: String,
    content: String,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.ingest(&project_id, &author_id, &content).await
}

#[tauri::command]
async fn search(
    core: State<'_, DesktopCore>,
    project_id: String,
    q: String,
    limit: usize,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.search(&project_id, &q, limit).await
}

#[tauri::command]
async fn semantic_search(
    core: State<'_, DesktopCore>,
    project_id: String,
    q: String,
    limit: usize,
) -> Result<String, String> {
    let core = core.inner().clone();
    core.semantic_search(&project_id, &q, limit).await
}

/// Launch the desktop app. The SQLite store lives next to the executable's
/// working directory for this spike; a production shell would resolve the OS
/// app-data directory via Tauri's path API (noted future).
pub fn run() {
    let core = DesktopCore::open("agistack-desktop.db").expect("open desktop sqlite store");
    tauri::Builder::default()
        .manage(core)
        .invoke_handler(tauri::generate_handler![ingest, search, semantic_search])
        .run(tauri::generate_context!())
        .expect("error while running the agistack desktop application");
}

#[cfg(test)]
mod tests {
    use super::*;

    // Headless proof: the desktop wiring (core + SQLite device adapters) runs a
    // full ingest -> keyword search -> semantic search round-trip WITHOUT a
    // webview. This is the "headless fallback" called out in 05-roadmap §4.4.
    #[test]
    fn desktop_core_round_trip_headless() {
        // A tiny single-threaded executor — no tokio in the test, mirroring the
        // core's runtime-agnostic contract.
        let core = DesktopCore::in_memory().expect("in-memory wiring");
        futures::executor::block_on(async {
            let created = core
                .ingest("p1", "u1", "Local-first desktop apps persist data in sqlite")
                .await
                .expect("ingest");
            assert!(created.contains("\"id\""), "ingest returns a memory json");

            let hits: serde_json::Value =
                serde_json::from_str(&core.search("p1", "sqlite", 10).await.unwrap()).unwrap();
            assert_eq!(hits.as_array().unwrap().len(), 1, "keyword hit");

            let miss: serde_json::Value =
                serde_json::from_str(&core.search("p1", "postgres", 10).await.unwrap()).unwrap();
            assert!(miss.as_array().unwrap().is_empty(), "keyword miss");

            let sem: serde_json::Value = serde_json::from_str(
                &core.semantic_search("p1", "on-device storage", 5).await.unwrap(),
            )
            .unwrap();
            assert!(!sem.as_array().unwrap().is_empty(), "semantic hit");
        });
    }
}
