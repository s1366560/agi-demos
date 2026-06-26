//! Portable, dependency-light adapters used by the spike.
//!
//! Everything here compiles to native, wasm, iOS and Android unchanged
//! (the only platform split is `SystemClock`, gated off wasm).

use std::collections::HashMap;
use std::sync::Mutex;

use async_trait::async_trait;
use memstack_core::model::{Episode, Memory};
use memstack_core::ports::{
    Clock, CoreError, CoreResult, EmbeddingPort, LlmPort, MemoryDraft, MemoryRepository,
};
use memstack_core::util::fnv1a;

/// In-memory repository (stands in for Postgres on server / SQLite on device).
#[derive(Default)]
pub struct InMemoryMemoryRepository {
    store: Mutex<HashMap<String, Memory>>,
}

impl InMemoryMemoryRepository {
    pub fn new() -> Self {
        Self::default()
    }
}

#[async_trait]
impl MemoryRepository for InMemoryMemoryRepository {
    async fn save(&self, memory: Memory) -> CoreResult<Memory> {
        let mut store = self
            .store
            .lock()
            .map_err(|_| CoreError::Storage("poisoned lock".into()))?;
        store.insert(memory.id.clone(), memory.clone());
        Ok(memory)
    }

    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>> {
        let store = self
            .store
            .lock()
            .map_err(|_| CoreError::Storage("poisoned lock".into()))?;
        Ok(store.get(id).cloned())
    }

    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        let store = self
            .store
            .lock()
            .map_err(|_| CoreError::Storage("poisoned lock".into()))?;
        let mut items: Vec<Memory> = store
            .values()
            .filter(|m| m.project_id == project_id)
            .cloned()
            .collect();
        items.sort_by(|a, b| b.created_at_ms.cmp(&a.created_at_ms));
        Ok(items.into_iter().skip(offset).take(limit).collect())
    }

    async fn delete(&self, id: &str) -> CoreResult<bool> {
        let mut store = self
            .store
            .lock()
            .map_err(|_| CoreError::Storage("poisoned lock".into()))?;
        Ok(store.remove(id).is_some())
    }
}

/// Deterministic stand-in for a real LLM "extract memory" step. Offline + pure,
/// so the spike runs with zero network and is reproducible in tests.
pub struct StubLlm;

#[async_trait]
impl LlmPort for StubLlm {
    async fn extract_memory(&self, episode: &Episode) -> CoreResult<MemoryDraft> {
        let content = episode.content.trim().to_string();
        let title = content
            .lines()
            .next()
            .unwrap_or("Untitled")
            .chars()
            .take(60)
            .collect::<String>();
        let mut tags: Vec<String> = content
            .split_whitespace()
            .filter(|w| w.len() > 5)
            .map(|w| w.to_lowercase())
            .collect();
        tags.sort();
        tags.dedup();
        tags.truncate(5);
        Ok(MemoryDraft {
            title,
            content,
            tags,
            entities: vec![],
        })
    }
}

/// Deterministic hashing embedding (stand-in for a real embedding model).
pub struct HashEmbedding {
    dim: usize,
}

impl HashEmbedding {
    pub fn new(dim: usize) -> Self {
        Self { dim }
    }
}

#[async_trait]
impl EmbeddingPort for HashEmbedding {
    async fn embed(&self, text: &str) -> CoreResult<Vec<f32>> {
        let mut v = vec![0f32; self.dim];
        for token in text.split_whitespace() {
            let h = fnv1a(&token.to_lowercase());
            v[(h as usize) % self.dim] += 1.0;
        }
        let norm = v.iter().map(|x| x * x).sum::<f32>().sqrt();
        if norm > 0.0 {
            for x in &mut v {
                *x /= norm;
            }
        }
        Ok(v)
    }
}

/// Fixed clock — works on every platform (used in tests / wasm).
pub struct FixedClock(pub i64);

impl Clock for FixedClock {
    fn now_ms(&self) -> i64 {
        self.0
    }
}

/// System clock — native only. `std::time` is unavailable on wasm32-unknown-unknown,
/// which is exactly why [`Clock`] is a port instead of a hardcoded call.
#[cfg(not(target_arch = "wasm32"))]
pub struct SystemClock;

#[cfg(not(target_arch = "wasm32"))]
impl Clock for SystemClock {
    fn now_ms(&self) -> i64 {
        use std::time::{SystemTime, UNIX_EPOCH};
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map(|d| d.as_millis() as i64)
            .unwrap_or(0)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use memstack_core::{Episode, MemoryService, SourceType};
    use std::sync::Arc;

    /// Risk #1 falsification: the core async pipeline runs under a *generic*
    /// executor (`futures::executor::block_on`) with NO tokio in sight.
    #[test]
    fn ingest_and_search_runs_without_tokio() {
        let service = MemoryService::new(
            Arc::new(InMemoryMemoryRepository::new()),
            Arc::new(StubLlm),
            Arc::new(HashEmbedding::new(8)),
            Arc::new(FixedClock(1_700_000_000_000)),
        );

        let episode = Episode {
            content: "Vector databases enable semantic memory retrieval".to_string(),
            source_type: SourceType::Text,
            valid_at_ms: 0,
            name: None,
            project_id: Some("p1".into()),
            user_id: None,
        };

        let memory =
            futures::executor::block_on(service.ingest_episode("p1", "u1", &episode)).unwrap();
        assert_eq!(memory.project_id, "p1");
        assert_eq!(memory.embedding.as_ref().unwrap().len(), 8);

        let hit = futures::executor::block_on(service.search("p1", "semantic", 10)).unwrap();
        assert_eq!(hit.len(), 1);
        assert_eq!(hit[0].id, memory.id);

        let miss = futures::executor::block_on(service.search("p1", "nonexistent", 10)).unwrap();
        assert_eq!(miss.len(), 0);
    }
}
