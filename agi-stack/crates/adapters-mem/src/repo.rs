//! In-memory [`MemoryRepository`] — stands in for Postgres on the server and
//! SQLite on device. Ported from the spike, unchanged except the import swap.

use std::collections::HashMap;
use std::sync::Mutex;

use agistack_core::model::Memory;
use agistack_core::ports::{CoreError, CoreResult, MemoryRepository};
use async_trait::async_trait;

/// A `HashMap`-backed repository. Project-scoped queries filter on `project_id`,
/// preserving the multi-tenancy invariant the Python repositories enforce.
#[derive(Default)]
pub struct InMemoryMemoryRepository {
    store: Mutex<HashMap<String, Memory>>,
}

impl InMemoryMemoryRepository {
    pub fn new() -> Self {
        Self::default()
    }
}

fn poisoned() -> CoreError {
    CoreError::Storage("poisoned lock".into())
}

#[async_trait]
impl MemoryRepository for InMemoryMemoryRepository {
    async fn save(&self, memory: Memory) -> CoreResult<Memory> {
        let mut store = self.store.lock().map_err(|_| poisoned())?;
        store.insert(memory.id.clone(), memory.clone());
        Ok(memory)
    }

    async fn find_by_id(&self, id: &str) -> CoreResult<Option<Memory>> {
        let store = self.store.lock().map_err(|_| poisoned())?;
        Ok(store.get(id).cloned())
    }

    async fn list_by_project(
        &self,
        project_id: &str,
        limit: usize,
        offset: usize,
    ) -> CoreResult<Vec<Memory>> {
        let store = self.store.lock().map_err(|_| poisoned())?;
        let mut items: Vec<Memory> = store
            .values()
            .filter(|m| m.project_id == project_id)
            .cloned()
            .collect();
        // Newest first, deterministic — matches the SQL `ORDER BY created_at DESC`.
        items.sort_by(|a, b| {
            b.created_at_ms
                .cmp(&a.created_at_ms)
                .then_with(|| a.id.cmp(&b.id))
        });
        Ok(items.into_iter().skip(offset).take(limit).collect())
    }

    async fn delete(&self, id: &str) -> CoreResult<bool> {
        let mut store = self.store.lock().map_err(|_| poisoned())?;
        Ok(store.remove(id).is_some())
    }
}
