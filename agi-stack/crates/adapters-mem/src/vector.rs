//! In-memory [`VectorIndexPort`]: a brute-force, project-scoped cosine index.
//!
//! This is the browser/test tier of the vector port (`01-portable-core.md` §3):
//! on the server the same port is pgvector, on device sqlite-vec, here a linear
//! scan. Brute force is fine at small N and keeps the adapter dependency-free and
//! wasm-compatible.

use std::collections::HashMap;
use std::sync::Mutex;

use agistack_core::ports::{CoreError, CoreResult, ScoredId, VectorIndexPort};
use async_trait::async_trait;

/// `(project_id, id) -> vector`. Keying by project keeps tenants isolated:
/// [`query`](InMemoryVectorIndex::query) never scans across project boundaries.
#[derive(Default)]
pub struct InMemoryVectorIndex {
    store: Mutex<HashMap<(String, String), Vec<f32>>>,
}

impl InMemoryVectorIndex {
    pub fn new() -> Self {
        Self::default()
    }
}

/// Cosine similarity (higher = closer). Returns 0 for a zero-norm vector.
fn cosine(a: &[f32], b: &[f32]) -> f32 {
    if a.len() != b.len() {
        return 0.0;
    }
    let dot: f32 = a.iter().zip(b).map(|(x, y)| x * y).sum();
    let na: f32 = a.iter().map(|x| x * x).sum::<f32>().sqrt();
    let nb: f32 = b.iter().map(|x| x * x).sum::<f32>().sqrt();
    if na == 0.0 || nb == 0.0 {
        0.0
    } else {
        dot / (na * nb)
    }
}

fn poisoned() -> CoreError {
    CoreError::Vector("poisoned lock".into())
}

#[async_trait]
impl VectorIndexPort for InMemoryVectorIndex {
    async fn upsert(&self, project_id: &str, id: &str, vector: &[f32]) -> CoreResult<()> {
        let mut store = self.store.lock().map_err(|_| poisoned())?;
        store.insert((project_id.to_string(), id.to_string()), vector.to_vec());
        Ok(())
    }

    async fn query(&self, project_id: &str, vector: &[f32], k: usize) -> CoreResult<Vec<ScoredId>> {
        let store = self.store.lock().map_err(|_| poisoned())?;
        let mut scored: Vec<ScoredId> = store
            .iter()
            .filter(|((p, _), _)| p == project_id)
            .map(|((_, id), v)| ScoredId {
                id: id.clone(),
                score: cosine(vector, v),
            })
            .collect();
        // Highest score first; tie-break on id for determinism.
        scored.sort_by(|a, b| {
            b.score
                .partial_cmp(&a.score)
                .unwrap_or(std::cmp::Ordering::Equal)
                .then_with(|| a.id.cmp(&b.id))
        });
        scored.truncate(k);
        Ok(scored)
    }

    async fn remove(&self, project_id: &str, id: &str) -> CoreResult<()> {
        let mut store = self.store.lock().map_err(|_| poisoned())?;
        store.remove(&(project_id.to_string(), id.to_string()));
        Ok(())
    }
}
