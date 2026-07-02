//! In-memory [`ChangeLog`] — the Phase-4 sync seam (`01-portable-core.md` §5).
//!
//! Recording local mutations now, behind a stable port, lets adapters start
//! emitting change events before the CRDT/delta-sync engine exists. This is the
//! **data-plane** capture side of control/data-plane separation
//! (`08-control-data-plane-separation.md` §7): the sync layer is the consumer.

use std::sync::Mutex;

use agistack_core::ports::{ChangeEvent, ChangeLog, CoreError, CoreResult};
use async_trait::async_trait;

/// Append-only log of [`ChangeEvent`]s, in order of arrival.
#[derive(Default)]
pub struct InMemoryChangeLog {
    events: Mutex<Vec<ChangeEvent>>,
}

impl InMemoryChangeLog {
    pub fn new() -> Self {
        Self::default()
    }

    /// Snapshot of everything recorded so far (for inspection / tests / the
    /// future sync flush).
    pub fn events(&self) -> Vec<ChangeEvent> {
        self.events.lock().expect("poisoned").clone()
    }
}

#[async_trait]
impl ChangeLog for InMemoryChangeLog {
    async fn record(&self, event: ChangeEvent) -> CoreResult<()> {
        self.events
            .lock()
            .map_err(|_| CoreError::Storage("poisoned lock".into()))?
            .push(event);
        Ok(())
    }
}
