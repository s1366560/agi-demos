use super::*;

#[tokio::test]
async fn database_renewal_can_keep_a_locally_expired_owner_snapshot_current() {
    let store = Arc::new(FakeStore::default());
    let ownership = Arc::new(FakeOwnership {
        current: true,
        checks: Mutex::new(0),
    });
    let execute = handler(
        CronOperationKind::ExecuteRun,
        CronOperationHandlerOutcome::Accepted {
            dispatch_json: json!({}),
        },
    );
    let snapshot = CronSchedulerLease {
        acquired_at: now() - chrono::Duration::seconds(60),
        lease_expires_at: now() - chrono::Duration::seconds(1),
        ..authority()
    };
    let report = worker_with_ownership(store.clone(), ownership.clone(), ready_config(), execute)
        .drain_once(&snapshot)
        .await
        .unwrap();
    assert_eq!(report.gate, None);
    assert_eq!(store.snapshot().claims, 1);
    assert_eq!(*ownership.checks.lock().unwrap(), 1);
}
