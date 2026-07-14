use std::sync::Mutex;

use agistack_adapters_postgres::{AutomationPayload, AutomationRunStatus, CronOperationStatus};
use agistack_core::agent::HitlRequest;
use chrono::Duration as ChronoDuration;
use serde_json::Value;

use super::*;

#[derive(Debug)]
struct FixedClock(DateTime<Utc>);

impl CronWorkerClock for FixedClock {
    fn now(&self) -> DateTime<Utc> {
        self.0
    }
}

#[derive(Debug)]
struct FixedId(&'static str);

impl ConversationIdFactory for FixedId {
    fn fresh_id(&self) -> String {
        self.0.to_string()
    }
}

struct FakeDispatchStore {
    result: Mutex<Option<Result<AutomationRunContext, AutomationRuntimeRepositoryError>>>,
    observed_fresh_id: Mutex<Option<String>>,
}

#[async_trait]
impl AutomationDispatchStore for FakeDispatchStore {
    async fn prepare_dispatch(
        &self,
        _operation: &CronOperationRecord,
        fresh_conversation_id: &str,
        _now: DateTime<Utc>,
    ) -> Result<AutomationRunContext, AutomationRuntimeRepositoryError> {
        *self.observed_fresh_id.lock().expect("fresh id lock") =
            Some(fresh_conversation_id.to_string());
        self.result
            .lock()
            .expect("dispatch result lock")
            .take()
            .expect("one dispatch result")
    }
}

fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-07-14T10:00:00Z")
        .expect("fixed time")
        .with_timezone(&Utc)
}

fn context() -> AutomationRunContext {
    AutomationRunContext {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        job_id: "job-1".to_string(),
        run_id: "run-1".to_string(),
        runtime_execution_id: "run-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        actor_user_id: "user-1".to_string(),
        actor_api_key_id: None,
        payload: AutomationPayload::AgentTurn {
            message: "prepare report".to_string(),
        },
        timeout_seconds: 60,
        status: AutomationRunStatus::Queued,
    }
}

fn operation() -> CronOperationRecord {
    CronOperationRecord {
        id: "operation-1".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        job_id: "job-1".to_string(),
        job_revision: 1,
        schedule_revision: Some(1),
        kind: CronOperationKind::ExecuteRun,
        run_id: Some("run-1".to_string()),
        trigger_type: Some("manual".to_string()),
        scheduled_for: None,
        input_json: json!({"runtime_execution_id": "run-1"}),
        status: CronOperationStatus::Processing,
        attempt_count: 1,
        max_attempts: 4,
        next_attempt_at: None,
        lease_owner: Some("worker-1".to_string()),
        lease_token: Some("lease-1".to_string()),
        lease_expires_at: Some(now() + ChronoDuration::seconds(30)),
        actor_user_id: Some("user-1".to_string()),
        actor_api_key_id: None,
        request_receipt_id: None,
        last_error_code: None,
        last_error_redacted: None,
        result_json: json!({}),
        created_at: now(),
        updated_at: now(),
        started_at: Some(now()),
        completed_at: None,
    }
}

#[tokio::test]
async fn execute_dispatch_accepts_only_after_durable_context_preparation() {
    let store = Arc::new(FakeDispatchStore {
        result: Mutex::new(Some(Ok(context()))),
        observed_fresh_id: Mutex::new(None),
    });
    let handler = ExecuteRunDispatchHandler::new(
        store.clone(),
        Arc::new(FixedClock(now())),
        Arc::new(FixedId("fresh-conversation")),
    );

    let outcome = handler
        .handle(&operation())
        .await
        .expect("dispatch outcome");

    let CronOperationHandlerOutcome::Accepted { dispatch_json } = outcome else {
        panic!("execute dispatch must be accepted");
    };
    assert_eq!(dispatch_json["runtime_execution_id"], "run-1");
    assert_eq!(dispatch_json["conversation_id"], "conversation-1");
    assert_eq!(
        store
            .observed_fresh_id
            .lock()
            .expect("fresh id lock")
            .as_deref(),
        Some("fresh-conversation")
    );
}

#[tokio::test]
async fn execute_dispatch_maps_structural_validation_to_closed_failure_code() {
    let handler = ExecuteRunDispatchHandler::new(
        Arc::new(FakeDispatchStore {
            result: Mutex::new(Some(Err(AutomationRuntimeRepositoryError::StaleRevision))),
            observed_fresh_id: Mutex::new(None),
        }),
        Arc::new(FixedClock(now())),
        Arc::new(FixedId("fresh-conversation")),
    );

    let outcome = handler.handle(&operation()).await.expect("typed failure");

    let CronOperationHandlerOutcome::RetryOrDeadLetter(failure) = outcome else {
        panic!("stale revision must not be accepted");
    };
    assert_eq!(failure.code, CronOperationErrorCode::StaleRevision);
    assert!(!failure.redacted_text.contains("job-1"));
}

#[derive(Debug, Default)]
struct RuntimeState {
    claims: Vec<AutomationRunLease>,
    renew: bool,
    waiting_calls: usize,
    projections: Vec<AutomationTerminalOutcome>,
    recovered: usize,
}

#[derive(Debug, Default)]
struct FakeRuntimeStore {
    state: Mutex<RuntimeState>,
}

#[async_trait]
impl AutomationRuntimeStore for FakeRuntimeStore {
    async fn claim_due(
        &self,
        _scope: &AutomationRuntimeScope,
        _limit: i64,
        _lease_owner: &str,
        _lease_seconds: i64,
        _now: DateTime<Utc>,
    ) -> Result<Vec<AutomationRunLease>, AutomationRuntimeRepositoryError> {
        Ok(std::mem::take(
            &mut self.state.lock().expect("runtime state lock").claims,
        ))
    }

    async fn renew(
        &self,
        _lease: &AutomationRunLease,
        _lease_seconds: i64,
        _now: DateTime<Utc>,
    ) -> CoreResult<bool> {
        Ok(self.state.lock().expect("runtime state lock").renew)
    }

    async fn mark_waiting_human(
        &self,
        _lease: &AutomationRunLease,
        _observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        self.state.lock().expect("runtime state lock").waiting_calls += 1;
        Ok(true)
    }

    async fn project_terminal(
        &self,
        _lease: &AutomationRunLease,
        _result: AutomationExecutionResult,
        outcome: AutomationTerminalOutcome,
        _error_code: Option<&str>,
        _observed_at: DateTime<Utc>,
    ) -> Result<AutomationTerminalProjection, AutomationRuntimeRepositoryError> {
        self.state
            .lock()
            .expect("runtime state lock")
            .projections
            .push(outcome);
        Ok(AutomationTerminalProjection {
            matched: true,
            duplicate: false,
            run_status: None,
            operation_status: Some("completed".to_string()),
            delivery_ack_pending: false,
        })
    }

    async fn recover_expired(
        &self,
        _scope: &AutomationRuntimeScope,
        _limit: i64,
        _now: DateTime<Utc>,
    ) -> Result<usize, AutomationRuntimeRepositoryError> {
        Ok(self.state.lock().expect("runtime state lock").recovered)
    }
}

#[derive(Debug)]
struct FakeExecutor {
    result: AutomationExecutionResult,
    delay: Duration,
}

#[async_trait]
impl AutomationRunExecutor for FakeExecutor {
    async fn execute(&self, _lease: &AutomationRunLease) -> CoreResult<AutomationExecutionResult> {
        sleep(self.delay).await;
        Ok(self.result)
    }
}

fn lease(deadline_at: DateTime<Utc>) -> AutomationRunLease {
    AutomationRunLease {
        context: AutomationRunContext {
            status: AutomationRunStatus::Running,
            ..context()
        },
        runtime_revision: 1,
        lease_owner: "runtime-worker".to_string(),
        lease_token: "runtime-lease".to_string(),
        lease_expires_at: now() + ChronoDuration::seconds(30),
        deadline_at,
    }
}

fn scope() -> AutomationRuntimeScope {
    AutomationRuntimeScope {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
    }
}

fn worker(
    store: Arc<FakeRuntimeStore>,
    result: AutomationExecutionResult,
    delay: Duration,
) -> CronAutomationRuntimeWorker {
    CronAutomationRuntimeWorker::new(
        store,
        Arc::new(FakeExecutor { result, delay }),
        AutomationRuntimeWorkerConfig {
            worker_id: "runtime-worker".to_string(),
            batch_size: 4,
            lease_seconds: 60,
            heartbeat_interval: Duration::from_millis(2),
        },
    )
}

#[tokio::test]
async fn runtime_worker_projects_success_after_executor_finishes() {
    let store = Arc::new(FakeRuntimeStore {
        state: Mutex::new(RuntimeState {
            claims: vec![lease(now() + ChronoDuration::seconds(30))],
            renew: true,
            ..Default::default()
        }),
    });
    let runtime = worker(
        store.clone(),
        AutomationExecutionResult {
            boundary: AutomationExecutionBoundary::Finished,
            event_count: 3,
            execution_time_ms: 8,
        },
        Duration::ZERO,
    );

    let report = runtime.drain_once(&scope(), now()).await.expect("drain");

    assert_eq!(report.claimed, 1);
    assert_eq!(report.succeeded, 1);
    assert_eq!(
        store.state.lock().expect("runtime state lock").projections,
        vec![AutomationTerminalOutcome::Success]
    );
}

#[tokio::test]
async fn runtime_worker_suspends_for_human_without_terminal_projection() {
    let store = Arc::new(FakeRuntimeStore {
        state: Mutex::new(RuntimeState {
            claims: vec![lease(now() + ChronoDuration::seconds(30))],
            renew: true,
            ..Default::default()
        }),
    });
    let runtime = worker(
        store.clone(),
        AutomationExecutionResult {
            boundary: AutomationExecutionBoundary::AwaitingHuman,
            event_count: 2,
            execution_time_ms: 5,
        },
        Duration::ZERO,
    );

    let report = runtime.drain_once(&scope(), now()).await.expect("drain");

    let state = store.state.lock().expect("runtime state lock");
    assert_eq!(report.waiting_human, 1);
    assert_eq!(state.waiting_calls, 1);
    assert!(state.projections.is_empty());
}

#[tokio::test]
async fn runtime_worker_stops_when_heartbeat_loses_the_fencing_lease() {
    let store = Arc::new(FakeRuntimeStore {
        state: Mutex::new(RuntimeState {
            claims: vec![lease(now() + ChronoDuration::seconds(30))],
            renew: false,
            ..Default::default()
        }),
    });
    let runtime = worker(
        store.clone(),
        AutomationExecutionResult {
            boundary: AutomationExecutionBoundary::Finished,
            event_count: 1,
            execution_time_ms: 20,
        },
        Duration::from_millis(20),
    );

    let report = runtime.drain_once(&scope(), now()).await.expect("drain");

    assert_eq!(report.lost_lease, 1);
    assert!(store
        .state
        .lock()
        .expect("runtime state lock")
        .projections
        .is_empty());
}

#[tokio::test]
async fn expired_claim_projects_timeout_without_starting_a_late_success() {
    let store = Arc::new(FakeRuntimeStore {
        state: Mutex::new(RuntimeState {
            claims: vec![lease(now())],
            renew: true,
            ..Default::default()
        }),
    });
    let runtime = worker(
        store.clone(),
        AutomationExecutionResult {
            boundary: AutomationExecutionBoundary::Finished,
            event_count: 1,
            execution_time_ms: 1,
        },
        Duration::ZERO,
    );

    let report = runtime.drain_once(&scope(), now()).await.expect("drain");

    assert_eq!(report.timed_out, 1);
    assert_eq!(
        store.state.lock().expect("runtime state lock").projections,
        vec![AutomationTerminalOutcome::Timeout]
    );
}

#[test]
fn dispatch_payload_excludes_actor_and_prompt_content() {
    let value: Value = json!({
        "runtime_execution_id": context().runtime_execution_id,
        "conversation_id": context().conversation_id,
        "runtime_status": context().status.as_str(),
    });
    let serialized = value.to_string();
    assert!(!serialized.contains("prepare report"));
    assert!(!serialized.contains("user-1"));
}

#[derive(Debug, Default)]
struct FakeHitlStore {
    requests: Mutex<Vec<NewHitlRequestRecord>>,
}

#[async_trait]
impl AutomationHitlStore for FakeHitlStore {
    async fn insert_pending(&self, request: &NewHitlRequestRecord) -> CoreResult<bool> {
        self.requests
            .lock()
            .expect("HITL request lock")
            .push(request.clone());
        Ok(true)
    }
}

fn hitl_observer(store: Arc<FakeHitlStore>) -> AutomationHitlObserver {
    AutomationHitlObserver {
        store: Some(store),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        run_id: "run-1".to_string(),
        actor_user_id: "user-1".to_string(),
        expires_at: now() + ChronoDuration::seconds(60),
    }
}

#[tokio::test]
async fn automation_observer_persists_non_secret_hitl_with_run_correlation() {
    let store = Arc::new(FakeHitlStore::default());
    let observer = hitl_observer(store.clone());
    let request = HitlRequest::new("request-1", HitlKind::Permission, "Allow the write?");

    observer
        .on_human_request("run-1", 2, &request)
        .await
        .expect("persist HITL");

    let requests = store.requests.lock().expect("HITL request lock");
    assert_eq!(requests.len(), 1);
    assert_eq!(requests[0].request_type, "permission");
    assert_eq!(requests[0].message_id.as_deref(), Some("run-1"));
    assert_eq!(
        requests[0].request_metadata.as_ref().expect("metadata")["automation_run_id"],
        "run-1"
    );
}

#[tokio::test]
async fn automation_observer_rejects_env_var_before_persistence() {
    let store = Arc::new(FakeHitlStore::default());
    let observer = hitl_observer(store.clone());
    let request = HitlRequest::new("request-secret", HitlKind::EnvVar, "Provide the token");

    let error = observer
        .on_human_request("run-1", 2, &request)
        .await
        .expect_err("env-var must stay fail closed");

    assert!(error.to_string().contains("sealed response"));
    assert!(store.requests.lock().expect("HITL request lock").is_empty());
}
