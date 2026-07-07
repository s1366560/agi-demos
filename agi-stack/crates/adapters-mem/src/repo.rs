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

    /// Return a deterministic copy of every in-memory record.
    ///
    /// This is intentionally a concrete-adapter helper, not a core port method:
    /// browser shells can serialize it into IndexedDB/local durable storage
    /// without forcing every production repository to expose a bulk dump API.
    pub fn snapshot(&self) -> CoreResult<Vec<Memory>> {
        let store = self.store.lock().map_err(|_| poisoned())?;
        let mut items: Vec<Memory> = store.values().cloned().collect();
        items.sort_by(|a, b| {
            a.project_id
                .cmp(&b.project_id)
                .then_with(|| b.created_at_ms.cmp(&a.created_at_ms))
                .then_with(|| a.id.cmp(&b.id))
        });
        Ok(items)
    }

    /// Replace the adapter state with a caller-supplied snapshot.
    pub fn replace_all(&self, memories: impl IntoIterator<Item = Memory>) -> CoreResult<()> {
        let mut store = self.store.lock().map_err(|_| poisoned())?;
        store.clear();
        for memory in memories {
            store.insert(memory.id.clone(), memory);
        }
        Ok(())
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

#[cfg(test)]
mod tests {
    use super::*;

    fn memory(id: &str, project_id: &str, created_at_ms: i64) -> Memory {
        Memory {
            id: id.to_string(),
            project_id: project_id.to_string(),
            title: format!("title {id}"),
            content: format!("content {id}"),
            author_id: "u1".to_string(),
            content_type: "text".to_string(),
            tags: Vec::new(),
            entities: Vec::new(),
            version: 1,
            status: "ENABLED".to_string(),
            created_at_ms,
            embedding: None,
        }
    }

    #[test]
    fn snapshot_is_deterministic_and_replace_all_restores_records() {
        let repo = InMemoryMemoryRepository::new();
        repo.replace_all([
            memory("b", "p2", 20),
            memory("a", "p1", 10),
            memory("c", "p1", 30),
        ])
        .unwrap();

        let snapshot = repo.snapshot().unwrap();
        assert_eq!(
            snapshot
                .iter()
                .map(|item| item.id.as_str())
                .collect::<Vec<_>>(),
            vec!["c", "a", "b"]
        );

        repo.replace_all([memory("restored", "p3", 40)]).unwrap();
        assert_eq!(
            repo.snapshot()
                .unwrap()
                .iter()
                .map(|item| item.id.as_str())
                .collect::<Vec<_>>(),
            vec!["restored"]
        );
    }
}
