struct DrainDeliverer {
    started: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Semaphore>,
}

#[async_trait]
impl ChannelMessageDeliverer for DrainDeliverer {
    async fn deliver(
        &self,
        _request: &ChannelDeliveryRequest,
    ) -> Result<ChannelDeliveryOutcome, ChannelDeliveryError> {
        self.started.notify_one();
        self.release
            .acquire()
            .await
            .expect("release delivery")
            .forget();
        Ok(ChannelDeliveryOutcome::Sent {
            channel_message_id: "delivered".to_string(),
        })
    }
}

#[tokio::test]
async fn delivery_worker_shutdown_drains_delivery_and_mark_before_next_claim() {
    let store = FakeStore::with_rows([outbox("first", "one"), outbox("next", "two")]);
    let started = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Semaphore::new(0));
    let mut config = worker_config(true, true);
    config.delivery.batch_limit = 1;
    config.poll_interval_millis = 60_000;
    let worker = Arc::new(ChannelOutboxDeliveryWorker::new(
        store.clone(),
        DrainDeliverer {
            started: started.clone(),
            release: release.clone(),
        },
        config,
    ));
    let runtime = worker.spawn_if_enabled().expect("worker starts");
    tokio::time::timeout(Duration::from_secs(2), started.notified())
        .await
        .unwrap();
    runtime.request_stop();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), runtime.shutdown())
            .await
            .is_err()
    );
    assert!(store.state.lock().unwrap().sent.is_empty());
    release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), runtime.shutdown())
        .await
        .unwrap()
        .unwrap();
    runtime.shutdown().await.unwrap();
    let state = store.state.lock().unwrap();
    assert_eq!(state.claim_calls, 1);
    assert_eq!(state.sent[0].0, "first");
    assert_eq!(state.queue[0].id, "next");
}

#[tokio::test]
async fn delivery_worker_drop_stops_claims_and_preserves_inflight_mark() {
    let store = FakeStore::with_rows([outbox("first", "one"), outbox("next", "two")]);
    let started = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Semaphore::new(0));
    let mut config = worker_config(true, true);
    config.delivery.batch_limit = 1;
    let worker = Arc::new(ChannelOutboxDeliveryWorker::new(
        store.clone(),
        DrainDeliverer {
            started: started.clone(),
            release: release.clone(),
        },
        config,
    ));
    let weak = Arc::downgrade(&worker);
    let runtime = worker.spawn_if_enabled().expect("worker starts");
    tokio::time::timeout(Duration::from_secs(2), started.notified())
        .await
        .unwrap();
    drop(runtime);
    assert!(weak.upgrade().is_some());
    release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), async {
        while weak.upgrade().is_some() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    let state = store.state.lock().unwrap();
    assert_eq!(state.claim_calls, 1);
    assert_eq!(state.sent[0].0, "first");
    assert_eq!(state.queue[0].id, "next");
}

struct DrainMarkStore {
    inner: FakeStore,
    marking: Arc<tokio::sync::Notify>,
    release: Arc<tokio::sync::Semaphore>,
}

#[async_trait]
impl ChannelOutboxDeliveryStore for DrainMarkStore {
    async fn claim_due_outbox(
        &self,
        worker_id: &str,
        lease_seconds: i64,
        limit: i64,
    ) -> Result<Vec<ChannelOutboxRecord>, ChannelApiError> {
        self.inner
            .claim_due_outbox(worker_id, lease_seconds, limit)
            .await
    }

    async fn mark_outbox_sent(
        &self,
        outbox_id: &str,
        worker_id: &str,
        message_id: &str,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
        self.marking.notify_one();
        self.release
            .acquire()
            .await
            .expect("release store")
            .forget();
        self.inner
            .mark_outbox_sent(outbox_id, worker_id, message_id)
            .await
    }

    async fn mark_outbox_failed(
        &self,
        outbox_id: &str,
        worker_id: &str,
        error: &str,
        retry_after_seconds: i64,
    ) -> Result<Option<ChannelOutboxRecord>, ChannelApiError> {
        self.inner
            .mark_outbox_failed(outbox_id, worker_id, error, retry_after_seconds)
            .await
    }
}

#[tokio::test]
async fn delivery_worker_shutdown_waits_for_persisted_mark() {
    let store = FakeStore::with_rows([outbox("first", "one"), outbox("next", "two")]);
    let marking = Arc::new(tokio::sync::Notify::new());
    let release = Arc::new(tokio::sync::Semaphore::new(0));
    let mut config = worker_config(true, true);
    config.delivery.batch_limit = 1;
    let runtime = Arc::new(ChannelOutboxDeliveryWorker::new(
        DrainMarkStore {
            inner: store.clone(),
            marking: marking.clone(),
            release: release.clone(),
        },
        FakeDeliverer::default(),
        config,
    ))
    .spawn_if_enabled()
    .expect("worker starts");
    tokio::time::timeout(Duration::from_secs(2), marking.notified())
        .await
        .unwrap();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), runtime.shutdown())
            .await
            .is_err()
    );
    assert!(store.state.lock().unwrap().sent.is_empty());
    release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), runtime.shutdown())
        .await
        .unwrap()
        .unwrap();
    let state = store.state.lock().unwrap();
    assert_eq!(state.claim_calls, 1);
    assert_eq!(state.sent[0].0, "first");
    assert_eq!(state.queue[0].id, "next");
}
