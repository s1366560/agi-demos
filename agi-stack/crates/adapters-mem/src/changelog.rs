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
    pub fn events(&self) -> CoreResult<Vec<ChangeEvent>> {
        Ok(self.events.lock().map_err(|_| poisoned())?.clone())
    }
}

fn poisoned() -> CoreError {
    CoreError::Storage("poisoned change log lock".into())
}

#[async_trait]
impl ChangeLog for InMemoryChangeLog {
    async fn record(&self, event: ChangeEvent) -> CoreResult<()> {
        self.events.lock().map_err(|_| poisoned())?.push(event);
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use futures::executor::block_on;

    static PANIC_HOOK_LOCK: Mutex<()> = Mutex::new(());

    fn event() -> ChangeEvent {
        ChangeEvent {
            entity: "memory".into(),
            entity_id: "m1".into(),
            op: "create".into(),
            version: 1,
            at_ms: 42,
        }
    }

    #[test]
    fn records_and_snapshots_events() {
        let log = InMemoryChangeLog::new();
        block_on(log.record(event())).unwrap();
        assert_eq!(log.events().unwrap().len(), 1);
    }

    #[test]
    fn poisoned_lock_returns_storage_error() {
        let log = InMemoryChangeLog::new();
        let _panic_hook_guard = PANIC_HOOK_LOCK.lock().unwrap();
        let old_hook = std::panic::take_hook();
        std::panic::set_hook(Box::new(|_| {}));
        let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            let _guard = log.events.lock().unwrap();
            panic!("poison change log mutex");
        }));
        std::panic::set_hook(old_hook);
        assert!(result.is_err());

        let err = block_on(log.record(event())).unwrap_err();
        assert!(matches!(
            err,
            CoreError::Storage(message) if message == "poisoned change log lock"
        ));
    }
}
