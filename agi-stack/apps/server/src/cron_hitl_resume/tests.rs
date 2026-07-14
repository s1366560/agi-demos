use std::sync::Mutex;

use super::*;

#[derive(Debug, Default)]
struct FakeState {
    candidates: Vec<AutomationHitlResumeCandidate>,
    accepted: Vec<String>,
    queued: Vec<String>,
    operations: Vec<String>,
}

#[derive(Debug, Default)]
struct FakeStore {
    state: Mutex<FakeState>,
    queue_result: Mutex<bool>,
}

#[async_trait]
impl AutomationHitlResumeStore for FakeStore {
    async fn list_candidates(
        &self,
        _scope: &AutomationRuntimeScope,
        _limit: i64,
        _now: DateTime<Utc>,
    ) -> CoreResult<Vec<AutomationHitlResumeCandidate>> {
        Ok(self
            .state
            .lock()
            .expect("resume state lock")
            .candidates
            .clone())
    }

    async fn queue_resume(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        _observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        self.state
            .lock()
            .expect("resume state lock")
            .queued
            .push(candidate.run_id.clone());
        self.state
            .lock()
            .expect("resume state lock")
            .operations
            .push(format!("queue:{}", candidate.run_id));
        Ok(*self.queue_result.lock().expect("queue result lock"))
    }
}

struct FakeAcceptor {
    state: Arc<FakeStore>,
    result: Mutex<Option<CoreResult<()>>>,
}

#[async_trait]
impl CheckpointAnswerAcceptor for FakeAcceptor {
    async fn accept(&self, candidate: &AutomationHitlResumeCandidate) -> CoreResult<()> {
        let mut state = self.state.state.lock().expect("resume state lock");
        state.accepted.push(candidate.request_id.clone());
        state
            .operations
            .push(format!("accept:{}", candidate.request_id));
        drop(state);
        self.result
            .lock()
            .expect("accept result lock")
            .take()
            .unwrap_or(Ok(()))
    }
}

fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-07-14T10:00:00Z")
        .expect("fixed time")
        .with_timezone(&Utc)
}

fn scope() -> AutomationRuntimeScope {
    AutomationRuntimeScope {
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
    }
}

fn candidate() -> AutomationHitlResumeCandidate {
    AutomationHitlResumeCandidate {
        request_id: "request-1".to_string(),
        request_type: "permission".to_string(),
        tenant_id: "tenant-1".to_string(),
        project_id: "project-1".to_string(),
        conversation_id: "conversation-1".to_string(),
        run_id: "run-1".to_string(),
        checkpoint_session_id: "run-1".to_string(),
        answer: "allow".to_string(),
    }
}

fn coordinator(
    queue_result: bool,
    accept_result: CoreResult<()>,
) -> (Arc<FakeStore>, CronHitlResumeCoordinator) {
    let store = Arc::new(FakeStore {
        state: Mutex::new(FakeState {
            candidates: vec![candidate()],
            ..Default::default()
        }),
        queue_result: Mutex::new(queue_result),
    });
    let acceptor = Arc::new(FakeAcceptor {
        state: Arc::clone(&store),
        result: Mutex::new(Some(accept_result)),
    });
    let coordinator = CronHitlResumeCoordinator::new(store.clone(), acceptor);
    (store, coordinator)
}

#[tokio::test]
async fn persists_checkpoint_answer_before_queueing_run() {
    let (store, coordinator) = coordinator(true, Ok(()));

    let report = coordinator
        .drain_once(&scope(), 10, now())
        .await
        .expect("resume drain");

    let state = store.state.lock().expect("resume state lock");
    assert_eq!(state.accepted, vec!["request-1"]);
    assert_eq!(state.queued, vec!["run-1"]);
    assert_eq!(state.operations, vec!["accept:request-1", "queue:run-1"]);
    assert_eq!(report.candidates, 1);
    assert_eq!(report.queued, 1);
    assert_eq!(report.lost_race, 0);
}

#[tokio::test]
async fn replay_after_checkpoint_crash_window_still_queues_run() {
    let (store, coordinator) = coordinator(true, Ok(()));

    let report = coordinator
        .drain_once(&scope(), 10, now())
        .await
        .expect("idempotent replay");

    assert_eq!(report.queued, 1);
    assert_eq!(
        store.state.lock().expect("resume state lock").accepted,
        vec!["request-1"]
    );
}

#[tokio::test]
async fn queue_compare_and_set_loss_is_reported_without_error() {
    let (_store, coordinator) = coordinator(false, Ok(()));

    let report = coordinator
        .drain_once(&scope(), 10, now())
        .await
        .expect("concurrent resume is idempotent");

    assert_eq!(report.queued, 0);
    assert_eq!(report.lost_race, 1);
}

#[tokio::test]
async fn checkpoint_failure_never_queues_run() {
    let (store, coordinator) = coordinator(
        true,
        Err(CoreError::Checkpoint("injected failure".to_string())),
    );

    let error = coordinator
        .drain_once(&scope(), 10, now())
        .await
        .expect_err("checkpoint failure");

    assert!(matches!(
        error,
        AutomationRuntimeRepositoryError::Storage(_)
    ));
    assert!(store
        .state
        .lock()
        .expect("resume state lock")
        .queued
        .is_empty());
}

#[tokio::test]
async fn unsupported_secret_candidate_fails_closed_before_checkpoint_or_queue() {
    let (store, coordinator) = coordinator(true, Ok(()));
    store.state.lock().expect("resume state lock").candidates[0].request_type =
        "env_var".to_string();

    let error = coordinator
        .drain_once(&scope(), 10, now())
        .await
        .expect_err("secret resume must be sealed first");

    assert_eq!(error, AutomationRuntimeRepositoryError::InvalidRunState);
    let state = store.state.lock().expect("resume state lock");
    assert!(state.accepted.is_empty());
    assert!(state.queued.is_empty());
}
