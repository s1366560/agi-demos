use super::*;
use std::sync::atomic::{AtomicBool, Ordering};

#[derive(Default)]
struct Store {
    value: Mutex<Option<String>>,
    fail_save: AtomicBool,
    fail_clear: AtomicBool,
}
impl TrustedSessionStore for Store {
    fn save_raw(&self, value: &str) -> Result<(), TrustedSessionStoreError> {
        if self.fail_save.load(Ordering::SeqCst) {
            return Err(TrustedSessionStoreError::Unavailable);
        }
        *self.value.lock().unwrap() = Some(value.into());
        Ok(())
    }
    fn load_raw(&self) -> Result<Option<String>, TrustedSessionStoreError> {
        Ok(self.value.lock().unwrap().clone())
    }
    fn clear_raw(&self) -> Result<(), TrustedSessionStoreError> {
        if self.fail_clear.load(Ordering::SeqCst) {
            return Err(TrustedSessionStoreError::Unavailable);
        }
        *self.value.lock().unwrap() = None;
        Ok(())
    }
}
fn record() -> TrustedSessionRecord {
    TrustedSessionRecord {
        version: 1,
        api_base_url: "https://example.test".into(),
        runtime_mode: TrustedSessionRuntimeMode::Cloud,
        credential_kind: TrustedSessionCredentialKind::CloudBearer,
        credential: "epoch-test-credential".into(),
        expires_at: None,
    }
}

#[test]
fn snapshots_distinguish_clear_and_restore_of_the_same_record() {
    let broker = TrustedSessionBroker::new(Arc::new(Store::default()));
    assert_eq!(broker.snapshot().unwrap().epoch, 0);
    broker.save(record()).unwrap();
    let before = broker.snapshot().unwrap();
    let clone = broker.clone();
    clone.clear().unwrap();
    clone.save(record()).unwrap();
    let after = broker.snapshot().unwrap();
    assert_eq!(after.record, before.record);
    assert_eq!(before.epoch, 1);
    assert_eq!(after.epoch, 3);
    let accepted = broker
        .with_snapshot(|current| current.epoch == before.epoch)
        .unwrap();
    assert!(!accepted);
    assert_eq!(broker.load().unwrap(), Some(record()));
    let debug = format!("{after:?}");
    assert!(!debug.contains("epoch-test-credential"));
}

#[test]
fn failed_storage_does_not_advance_epoch_and_successful_discard_does() {
    let store = Arc::new(Store::default());
    let broker = TrustedSessionBroker::new(store.clone());
    store.fail_save.store(true, Ordering::SeqCst);
    assert_eq!(
        broker.save(record()),
        Err(TrustedSessionBrokerError::StorageUnavailable)
    );
    assert_eq!(broker.snapshot().unwrap().epoch, 0);
    store.fail_save.store(false, Ordering::SeqCst);
    broker.save(record()).unwrap();
    store.fail_clear.store(true, Ordering::SeqCst);
    assert_eq!(
        broker.clear(),
        Err(TrustedSessionBrokerError::StorageUnavailable)
    );
    assert_eq!(broker.snapshot().unwrap().epoch, 1);
    *store.value.lock().unwrap() = Some("corrupt".into());
    assert_eq!(
        broker.load(),
        Err(TrustedSessionBrokerError::StorageUnavailable)
    );
    assert_eq!(*broker.operations.lock().unwrap(), 1);
    store.fail_clear.store(false, Ordering::SeqCst);
    assert_eq!(broker.load(), Err(TrustedSessionBrokerError::CorruptRecord));
    let discarded = broker.snapshot().unwrap();
    assert_eq!(discarded.epoch, 2);
    assert!(discarded.record.is_none());
    broker.clear().unwrap();
    assert_eq!(broker.snapshot().unwrap().epoch, 3);
}

#[test]
fn snapshot_callback_fences_clear_until_synchronous_commit_finishes() {
    let broker = TrustedSessionBroker::new(Arc::new(Store::default()));
    broker.save(record()).unwrap();
    let (entered_tx, entered_rx) = std::sync::mpsc::channel();
    let (done_tx, done_rx) = std::sync::mpsc::channel();
    let clone = broker.clone();
    let worker = broker
        .with_snapshot(|snapshot| {
            assert_eq!(snapshot.epoch, 1);
            let worker = std::thread::spawn(move || {
                entered_tx.send(()).unwrap();
                clone.clear().unwrap();
                done_tx.send(()).unwrap();
            });
            entered_rx
                .recv_timeout(std::time::Duration::from_secs(5))
                .unwrap();
            assert_eq!(
                done_rx.try_recv(),
                Err(std::sync::mpsc::TryRecvError::Empty)
            );
            worker
        })
        .unwrap();
    worker.join().unwrap();
    done_rx.recv().unwrap();
    assert_eq!(broker.snapshot().unwrap().epoch, 2);
}

#[test]
fn epoch_overflow_fails_before_changing_the_record() {
    let broker = TrustedSessionBroker::new(Arc::new(Store::default()));
    broker.save(record()).unwrap();
    *broker.operations.lock().unwrap() = u64::MAX;
    assert_eq!(
        broker.clear(),
        Err(TrustedSessionBrokerError::StorageUnavailable)
    );
    assert_eq!(
        broker.save(record()),
        Err(TrustedSessionBrokerError::StorageUnavailable)
    );
    assert_eq!(broker.load().unwrap(), Some(record()));
}
