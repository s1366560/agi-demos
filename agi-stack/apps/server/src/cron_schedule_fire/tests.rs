use std::sync::Mutex;

use agistack_adapters_postgres::{CronScheduleSnapshot, CronScheduleStatus};
use chrono::DateTime;
use serde_json::{json, Value};

use super::*;

#[derive(Debug)]
struct FixedClock(DateTime<Utc>);

impl CronWorkerClock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

struct FakeStore {
    candidates: Vec<CronDueSchedule>,
    requests: Mutex<Vec<(CronScheduleProjection, NewCronScheduledFire)>>,
    commit: bool,
}

#[async_trait]
impl CronScheduleFireStore for FakeStore {
    async fn list_due(
        &self,
        _scope: CronOperationScope<'_>,
        _now: DateTime<Utc>,
        _limit: i64,
    ) -> Result<Vec<CronDueSchedule>, CronScheduleFireError> {
        Ok(self.candidates.clone())
    }

    async fn commit_fire(
        &self,
        _scope: CronOperationScope<'_>,
        candidate: &CronDueSchedule,
        next: &CronScheduleProjection,
        fire: &NewCronScheduledFire,
        _observed_at: DateTime<Utc>,
    ) -> Result<Option<CronScheduledFireResult>, CronScheduleFireError> {
        self.requests
            .lock()
            .expect("request lock")
            .push((next.clone(), fire.clone()));
        Ok(self.commit.then(|| CronScheduledFireResult {
            run_id: fire.run_id.clone(),
            operation_id: fire.operation_id.clone(),
            scheduled_for: candidate.scheduled_for,
            schedule_status: next.status,
            next_fire_at: next.next_fire_at,
        }))
    }
}

fn ts(value: &str) -> DateTime<Utc> {
    DateTime::parse_from_rfc3339(value)
        .expect("fixed timestamp")
        .with_timezone(&Utc)
}

fn candidate(schedule_type: &str, schedule_config: Value) -> CronDueSchedule {
    let snapshot = CronScheduleSnapshot {
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
    };
    let fingerprint = project_schedule(&snapshot, ts("2026-07-14T09:59:00Z"))
        .expect("valid schedule")
        .schedule_fingerprint;
    CronDueSchedule {
        snapshot,
        schedule_fingerprint: fingerprint,
        scheduled_for: ts("2026-07-14T10:00:00Z"),
        actor_user_id: Some("user-1".to_string()),
        conversation_id: None,
        timeout_seconds: 300,
        max_retries: 3,
        delete_after_run: false,
    }
}

#[tokio::test]
async fn recurring_cursor_commits_one_run_without_dropping_missed_slots() {
    let mut overdue = candidate("every", json!({"interval_seconds": 60}));
    overdue.scheduled_for = ts("2026-07-14T09:58:00Z");
    let store = Arc::new(FakeStore {
        candidates: vec![overdue],
        requests: Mutex::new(Vec::new()),
        commit: true,
    });
    let coordinator = CronScheduleFireCoordinator::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:30Z"))),
    );

    let summary = coordinator
        .fire_due("tenant-1", "project-1", 10)
        .await
        .expect("fire due cursor");

    assert_eq!(summary.due, 1);
    assert_eq!(summary.committed, 1);
    assert_eq!(summary.lost_compare_and_set, 0);
    let requests = store.requests.lock().expect("request lock");
    assert_eq!(requests[0].0.status, CronScheduleStatus::Active);
    assert_eq!(requests[0].0.next_fire_at, Some(ts("2026-07-14T09:59:00Z")));
    assert_eq!(
        requests[0].1.run_id,
        deterministic_fire(&store.candidates[0]).run_id
    );
}

#[tokio::test]
async fn one_shot_cursor_becomes_exhausted_in_the_same_commit() {
    let store = Arc::new(FakeStore {
        candidates: vec![candidate("at", json!({"run_at": "2026-07-14T10:00:00Z"}))],
        requests: Mutex::new(Vec::new()),
        commit: true,
    });
    let coordinator = CronScheduleFireCoordinator::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))),
    );

    coordinator
        .fire_due("tenant-1", "project-1", 1)
        .await
        .expect("fire one shot");

    let requests = store.requests.lock().expect("request lock");
    assert_eq!(requests[0].0.status, CronScheduleStatus::Exhausted);
    assert_eq!(requests[0].0.next_fire_at, None);
}

#[tokio::test]
async fn competing_scheduler_cas_loss_is_counted_without_duplicate_success() {
    let store = Arc::new(FakeStore {
        candidates: vec![candidate("every", json!({"interval_seconds": 60}))],
        requests: Mutex::new(Vec::new()),
        commit: false,
    });
    let coordinator =
        CronScheduleFireCoordinator::new(store, Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))));

    let summary = coordinator
        .fire_due("tenant-1", "project-1", 1)
        .await
        .expect("CAS loss is benign");

    assert_eq!(summary.committed, 0);
    assert_eq!(summary.lost_compare_and_set, 1);
}

#[tokio::test]
async fn candidate_without_durable_actor_fails_before_any_commit() {
    let mut invalid = candidate("every", json!({"interval_seconds": 60}));
    invalid.actor_user_id = None;
    let store = Arc::new(FakeStore {
        candidates: vec![invalid],
        requests: Mutex::new(Vec::new()),
        commit: true,
    });
    let coordinator = CronScheduleFireCoordinator::new(
        store.clone(),
        Arc::new(FixedClock(ts("2026-07-14T10:00:00Z"))),
    );

    let error = coordinator
        .fire_due("tenant-1", "project-1", 1)
        .await
        .expect_err("missing actor must fail closed");

    assert!(error.to_string().contains("candidate is invalid"));
    assert!(store.requests.lock().expect("request lock").is_empty());
}
