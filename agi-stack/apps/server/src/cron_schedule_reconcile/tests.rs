use std::sync::Mutex;

use agistack_adapters_postgres::CronOperationStatus;
use serde_json::Value;

use super::*;

#[derive(Debug)]
struct FixedClock(DateTime<Utc>);

impl CronWorkerClock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

struct FakeStore {
    snapshot: Mutex<Option<Result<CronScheduleSnapshot, CronScheduleRepositoryError>>>,
    applied: Mutex<Vec<CronScheduleProjection>>,
    apply_result: Option<CronScheduleMaterializedState>,
}

#[async_trait]
impl CronScheduleStore for FakeStore {
    async fn load_target(
        &self,
        _operation: &CronOperationRecord,
    ) -> Result<CronScheduleSnapshot, CronScheduleRepositoryError> {
        self.snapshot
            .lock()
            .expect("snapshot lock")
            .take()
            .expect("one snapshot result")
    }

    async fn apply_projection(
        &self,
        _operation: &CronOperationRecord,
        projection: &CronScheduleProjection,
        _observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduleMaterializedState>, CronScheduleRepositoryError> {
        self.applied
            .lock()
            .expect("applied lock")
            .push(projection.clone());
        Ok(self.apply_result.clone())
    }
}

fn ts(value: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(value)
        .expect("fixed timestamp")
        .with_timezone(&Utc)
}

fn snapshot(schedule_type: &str, schedule_config: Value) -> CronScheduleSnapshot {
    CronScheduleSnapshot {
        job_id: "job-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        job_revision: 3,
        schedule_revision: 2,
        enabled: true,
        schedule_type: schedule_type.to_string(),
        schedule_config,
        timezone: "UTC".to_string(),
        stagger_seconds: 0,
        created_at: ts("2026-07-14T09:00:00Z"),
    }
}

fn operation() -> CronOperationRecord {
    CronOperationRecord {
        id: "operation-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        job_id: "job-1".to_string(),
        job_revision: 3,
        schedule_revision: Some(2),
        kind: CronOperationKind::ReconcileSchedule,
        run_id: None,
        trigger_type: None,
        scheduled_for: None,
        input_json: json!({}),
        status: CronOperationStatus::Processing,
        attempt_count: 1,
        max_attempts: 3,
        next_attempt_at: None,
        lease_owner: Some("worker-1".to_string()),
        lease_token: Some("lease-1".to_string()),
        lease_expires_at: Some(ts("2026-07-14T10:01:00Z")),
        actor_user_id: None,
        actor_api_key_id: None,
        request_receipt_id: None,
        last_error_code: None,
        last_error_redacted: None,
        result_json: json!({}),
        created_at: ts("2026-07-14T10:00:00Z"),
        updated_at: ts("2026-07-14T10:00:00Z"),
        started_at: Some(ts("2026-07-14T10:00:00Z")),
        completed_at: None,
    }
}

fn materialized() -> CronScheduleMaterializedState {
    CronScheduleMaterializedState {
        schedule_revision: 2,
        status: CronScheduleStatus::Active,
        schedule_fingerprint: "a".repeat(64),
        next_fire_at: Some(ts("2026-07-14T10:01:00Z")),
    }
}

#[test]
fn every_schedule_uses_durable_anchor_and_strictly_future_cursor() {
    let projection = project_schedule(
        &snapshot(
            "every",
            json!({"interval_seconds": 900, "anchor_at": "2026-07-14T09:00:00Z"}),
        ),
        ts("2026-07-14T10:00:00Z"),
    )
    .expect("valid interval");

    assert_eq!(projection.status, CronScheduleStatus::Active);
    assert_eq!(projection.next_fire_at, Some(ts("2026-07-14T10:15:00Z")));
}

#[test]
fn at_schedule_becomes_exhausted_after_its_fire_time() {
    let projection = project_schedule(
        &snapshot("at", json!({"run_at": "2026-07-14T09:59:59Z"})),
        ts("2026-07-14T10:00:00Z"),
    )
    .expect("valid one-shot");

    assert_eq!(projection.status, CronScheduleStatus::Exhausted);
    assert_eq!(projection.next_fire_at, None);
}

#[test]
fn cron_schedule_applies_iana_timezone_and_stagger_without_skipping_due_slot() {
    let mut target = snapshot(
        "cron",
        json!({"expr": "0 9 * * *", "timezone": "Asia/Shanghai"}),
    );
    target.stagger_seconds = 5;

    let projection =
        project_schedule(&target, ts("2026-07-14T00:59:59Z")).expect("valid timezone cron");

    assert_eq!(projection.next_fire_at, Some(ts("2026-07-14T01:00:05Z")));
}

#[tokio::test]
async fn handler_projects_then_returns_redacted_completion_metadata() {
    let store = Arc::new(FakeStore {
        snapshot: Mutex::new(Some(Ok(snapshot("every", json!({"interval_seconds": 60}))))),
        applied: Mutex::new(Vec::new()),
        apply_result: Some(materialized()),
    });
    let handler = ReconcileScheduleHandler::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))),
    );

    let outcome = handler.handle(&operation()).await.expect("handler outcome");

    let CronOperationHandlerOutcome::Complete { result_json } = outcome else {
        panic!("valid reconcile must complete");
    };
    assert_eq!(result_json["schedule_status"], "active");
    assert_eq!(result_json["next_fire_at"], "2026-07-14T10:01:00Z");
    assert!(result_json.get("schedule_config").is_none());
    assert_eq!(store.applied.lock().expect("applied lock").len(), 1);
}

#[tokio::test]
async fn invalid_schedule_fails_with_typed_code_without_writing_state() {
    let store = Arc::new(FakeStore {
        snapshot: Mutex::new(Some(Ok(snapshot("cron", json!({"expr": "not a cron"}))))),
        applied: Mutex::new(Vec::new()),
        apply_result: Some(materialized()),
    });
    let handler = ReconcileScheduleHandler::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))),
    );

    let outcome = handler.handle(&operation()).await.expect("typed failure");

    let CronOperationHandlerOutcome::RetryOrDeadLetter(failure) = outcome else {
        panic!("invalid schedule must fail closed");
    };
    assert_eq!(failure.code, CronOperationErrorCode::InvalidOperation);
    assert!(store.applied.lock().expect("applied lock").is_empty());
}

#[tokio::test]
async fn stale_source_revision_never_projects_schedule_state() {
    let store = Arc::new(FakeStore {
        snapshot: Mutex::new(Some(Err(CronScheduleRepositoryError::StaleRevision))),
        applied: Mutex::new(Vec::new()),
        apply_result: Some(materialized()),
    });
    let handler = ReconcileScheduleHandler::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))),
    );

    let outcome = handler
        .handle(&operation())
        .await
        .expect("typed stale failure");

    let CronOperationHandlerOutcome::RetryOrDeadLetter(failure) = outcome else {
        panic!("stale schedule must fail closed");
    };
    assert_eq!(failure.code, CronOperationErrorCode::StaleRevision);
    assert!(store.applied.lock().expect("applied lock").is_empty());
}
