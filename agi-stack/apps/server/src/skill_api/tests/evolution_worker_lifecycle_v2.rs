struct DrainExecutor {
    started: tokio::sync::Notify,
    release: tokio::sync::Semaphore,
}

#[async_trait]
impl SkillEvolutionRunExecutor for DrainExecutor {
    async fn execute(
        &self,
        _run: &SkillEvolutionRunRecord,
    ) -> Result<SkillEvolutionExecutionSummary, SkillApiError> {
        self.started.notify_one();
        self.release
            .acquire()
            .await
            .expect("release executor")
            .forget();
        Ok(SkillEvolutionExecutionSummary::skipped("test completion"))
    }
}

#[tokio::test]
async fn skill_worker_shutdown_drains_claimed_run_without_claiming_next() {
    use std::time::Duration;
    let queue = Arc::new(FakeRunQueue::with_run(sample_run_record("first")));
    queue
        .pending
        .lock()
        .unwrap()
        .push_back(sample_run_record("next"));
    let executor = Arc::new(DrainExecutor {
        started: tokio::sync::Notify::new(),
        release: tokio::sync::Semaphore::new(0),
    });
    let worker = Arc::new(PgSkillEvolutionWorker::with_parts(
        queue.clone(),
        executor.clone(),
        SkillEvolutionWorkerConfig {
            autostart: true,
            production_ready: true,
            poll_interval_millis: 60_000,
            ..Default::default()
        },
    ));
    let runtime = worker.spawn_if_enabled().expect("worker starts");
    tokio::time::timeout(Duration::from_secs(2), executor.started.notified())
        .await
        .unwrap();
    runtime.request_stop();
    assert!(
        tokio::time::timeout(Duration::from_millis(20), runtime.shutdown())
            .await
            .is_err()
    );
    assert!(queue.completed.lock().unwrap().is_empty());
    assert_eq!(queue.pending.lock().unwrap().len(), 1);
    executor.release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), runtime.shutdown())
        .await
        .unwrap()
        .unwrap();
    runtime.shutdown().await.unwrap();
    assert_eq!(queue.completed.lock().unwrap()[0].0, "first");
    assert_eq!(queue.pending.lock().unwrap()[0].id, "next");
}

#[tokio::test]
async fn skill_worker_drop_requests_stop_and_preserves_inflight_completion() {
    use std::time::Duration;
    let queue = Arc::new(FakeRunQueue::with_run(sample_run_record("first")));
    queue
        .pending
        .lock()
        .unwrap()
        .push_back(sample_run_record("next"));
    let executor = Arc::new(DrainExecutor {
        started: tokio::sync::Notify::new(),
        release: tokio::sync::Semaphore::new(0),
    });
    let worker = Arc::new(PgSkillEvolutionWorker::with_parts(
        queue.clone(),
        executor.clone(),
        SkillEvolutionWorkerConfig {
            autostart: true,
            production_ready: true,
            poll_interval_millis: 1,
            ..Default::default()
        },
    ));
    let weak = Arc::downgrade(&worker);
    let runtime = worker.spawn_if_enabled().expect("worker starts");
    tokio::time::timeout(Duration::from_secs(2), executor.started.notified())
        .await
        .unwrap();
    drop(runtime);
    assert!(
        weak.upgrade().is_some(),
        "inflight operation still owns worker"
    );
    executor.release.add_permits(1);
    tokio::time::timeout(Duration::from_secs(2), async {
        while weak.upgrade().is_some() {
            tokio::task::yield_now().await;
        }
    })
    .await
    .unwrap();
    assert_eq!(queue.completed.lock().unwrap()[0].0, "first");
    assert_eq!(queue.pending.lock().unwrap()[0].id, "next");
}
