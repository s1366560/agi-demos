//! In-memory [`CheckpointStore`] — the test/browser tier of agent crash recovery
//! (ADR-0005). The same port is SQLite on device and Postgres on the server.

use std::collections::HashMap;
use std::sync::Mutex;

use agistack_core::agent::types::SessionState;
use agistack_core::ports::{CheckpointStore, CoreError, CoreResult};
use async_trait::async_trait;

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
    pub fn seed(&self, state: SessionState) -> CoreResult<()> {
        self.store
            .lock()
            .map_err(|_| poisoned())?
            .insert(state.session_id.clone(), state);
        Ok(())
    }
}

fn poisoned() -> CoreError {
    CoreError::Checkpoint("poisoned checkpoint store lock".into())
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
        self.store
            .lock()
            .map_err(|_| poisoned())?
            .remove(session_id);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

    #[test]
    fn seed_installs_checkpoint() {
        let store = InMemoryCheckpointStore::new();
        let state = SessionState::new("session-1", "goal", Some("project-1"));
        store.seed(state).unwrap();
        assert!(block_on(store.load("session-1")).unwrap().is_some());
    }

    #[test]
    fn poisoned_lock_returns_checkpoint_error() {
        let store = InMemoryCheckpointStore::new();
        let _panic_hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let old_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = store.store.lock().unwrap();
            panic!("poison checkpoint mutex");
        }));
        std::panic::set_hook(old_hook);
        assert!(result.is_err());

        let err = block_on(store.load("session-1")).unwrap_err();
        assert!(matches!(
            err,
            CoreError::Checkpoint(message) if message == "poisoned checkpoint store lock"
        ));
    }
}
