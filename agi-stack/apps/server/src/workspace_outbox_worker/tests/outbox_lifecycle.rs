use super::*;

#[test]
fn workspace_plan_outbox_handlers_register_required_foundations() {
    let store = Arc::new(FakeWorkspacePlanDispatchStore::default());
    let handlers = workspace_plan_outbox_handlers(store as Arc<dyn WorkspacePlanDispatchStore>);

    assert!(missing_required_handler_event_types(&handlers).is_empty());
    assert!(handlers.contains_key(WORKSPACE_AGENT_MENTION_EVENT));
    assert_eq!(handlers.len(), required_handler_event_types().len() + 1);
}

#[tokio::test]
async fn workspace_outbox_worker_marks_registered_handler_completed() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-complete", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Complete))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            completed: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-complete");
    assert_eq!(item.status, "completed");
    assert!(item.processed_at.is_some());
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_worker_fails_missing_handler_without_dropping_job() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-missing", "unknown"));
    let worker = worker(Arc::clone(&store), HashMap::new());

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            failed: 1,
            missing_handler: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-missing");
    assert_eq!(item.status, "failed");
    assert_eq!(
        item.last_error.as_deref(),
        Some("no handler for event_type=unknown")
    );
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_worker_release_outcome_returns_attempt_budget() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-release", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Release))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            released: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-release");
    assert_eq!(item.status, "pending");
    assert_eq!(item.last_error.as_deref(), Some("shutdown"));
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_worker_does_not_claim_unhandled_pending_runtime_events() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    let mut item = outbox("job-future-runtime", "future_runtime_event");
    item.status = "pending_runtime".to_string();
    store.insert(item);
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([(
            "future_runtime_event".to_string(),
            handler(HandlerBehavior::Complete),
        )]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(report, WorkspacePlanOutboxRunReport::default());
    let item = store.get("job-future-runtime");
    assert_eq!(item.status, "pending_runtime");
    assert_eq!(item.attempt_count, 0);
    assert!(item.lease_owner.is_none());
}

#[tokio::test]
async fn workspace_outbox_worker_failed_handler_marks_retryable_failure() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-fail", "known"));
    let worker = worker(
        Arc::clone(&store),
        HashMap::from([("known".to_string(), handler(HandlerBehavior::Fail))]),
    );

    let report = worker.run_once().await.unwrap();

    assert_eq!(
        report,
        WorkspacePlanOutboxRunReport {
            claimed: 1,
            failed: 1,
            ..Default::default()
        }
    );
    let item = store.get("job-fail");
    assert_eq!(item.status, "failed");
    assert_eq!(
        item.last_error.as_deref(),
        Some("storage error: handler boom")
    );
    assert_eq!(item.attempt_count, 1);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_autostart_without_handlers() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", "unknown"));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: true,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        HashMap::new(),
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_partial_production_handlers() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", HANDOFF_RESUME_EVENT));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: true,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        HashMap::from([(
            HANDOFF_RESUME_EVENT.to_string(),
            handler(HandlerBehavior::Complete),
        )]),
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_refuses_autostart_without_production_ready_gate() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-safe", "known"));
    let mut handlers = required_handler_event_types()
        .into_iter()
        .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
        .collect::<WorkspacePlanOutboxHandlers>();
    handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            autostart: true,
            production_ready: false,
            ..WorkspacePlanOutboxWorkerConfig::default()
        },
        handlers,
    ));

    let runtime = worker.spawn_if_enabled();

    assert!(runtime.is_none());
    let item = store.get("job-safe");
    assert_eq!(item.status, "pending");
    assert_eq!(item.attempt_count, 0);
}

#[tokio::test]
async fn workspace_outbox_loop_polls_until_stopped_when_handlers_exist() {
    let store = Arc::new(FakeWorkspacePlanOutboxStore::default());
    store.insert(outbox("job-loop", "known"));
    let mut handlers = required_handler_event_types()
        .into_iter()
        .map(|event_type| (event_type.to_string(), handler(HandlerBehavior::Complete)))
        .collect::<WorkspacePlanOutboxHandlers>();
    handlers.insert("known".to_string(), handler(HandlerBehavior::Complete));
    let worker = Arc::new(WorkspacePlanOutboxWorker::new(
        Arc::clone(&store) as Arc<dyn WorkspacePlanOutboxStore>,
        WorkspacePlanOutboxWorkerConfig {
            worker_id: "worker-test".to_string(),
            batch_size: 10,
            lease_seconds: 60,
            poll_interval_millis: 5,
            autostart: true,
            production_ready: true,
        },
        handlers,
    ));
    let runtime = worker.spawn_if_enabled().expect("runtime should start");

    for _ in 0..20 {
        if store.get("job-loop").status == "completed" {
            runtime.shutdown().await;
            let item = store.get("job-loop");
            assert_eq!(item.status, "completed");
            assert_eq!(item.attempt_count, 1);
            return;
        }
        sleep(tokio::time::Duration::from_millis(5)).await;
    }
    runtime.shutdown().await;
    panic!("worker loop did not complete the job");
}
