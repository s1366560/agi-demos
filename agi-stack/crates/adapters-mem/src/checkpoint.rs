//! In-memory [`CheckpointStore`] — the test/browser tier of agent crash recovery
//! (ADR-0005). The same port is SQLite on device and Postgres on the server.

use std::collections::HashMap;
use std::sync::Mutex;

use async_trait::async_trait;
use agistack_core::agent::types::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};

/// `session_id -> latest SessionState`. `save` is insert-or-replace, so a round
/// boundary simply overwrites the prior checkpoint with the advanced state.
#[derive(Default)]
pub struct InMemoryCheckpointStore {
    store: Mutex<HashMap<String, SessionState>>,
}

impl InMemoryCheckpointStore {
    pub fn new() -> Self {
        Self::default()
    }

    /// Test/seed helper: install a checkpoint directly (e.g. to simulate a crash
    /// mid-round, then resume a fresh engine against it).
    pub fn seed(&self, state: SessionState) {
        self.store
            .lock()
            .expect("poisoned")
            .insert(state.session_id.clone(), state);
    }
}

fn poisoned() -> CoreError {
    CoreError::Checkpoint("poisoned lock".into())
}

#[async_trait]
impl CheckpointStore for InMemoryCheckpointStore {
    async fn save(&self, state: &SessionState) -> CoreResult<()> {
        self.store
            .lock()
            .map_err(|_| poisoned())?
            .insert(state.session_id.clone(), state.clone());
        Ok(())
    }

    async fn load(&self, session_id: &str) -> CoreResult<Option<SessionState>> {
        Ok(self
            .store
            .lock()
            .map_err(|_| poisoned())?
            .get(session_id)
            .cloned())
    }

    async fn delete(&self, session_id: &str) -> CoreResult<()> {
        self.store.lock().map_err(|_| poisoned())?.remove(session_id);
        Ok(())
    }
}
