use std::sync::Mutex;

use super::*;

struct FakeStore {
    candidates: Mutex<Vec<AutomationHitlResumeCandidate>>,
    admitted: Mutex<Vec<AutomationHitlResumeCandidate>>,
    result: Mutex<Option<Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError>>>,
}

#[async_trait]
impl AutomationHitlResumeStore for FakeStore {
    async fn list_candidates(
        &self,
        _scope: &AutomationRuntimeScope,
        _limit: i64,
        _now: DateTime<Utc>,
    ) -> CoreResult<Vec<AutomationHitlResumeCandidate>> {
        Ok(self.candidates.lock().unwrap().clone())
    }

    async fn admit_answer(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        _observed_at: DateTime<Utc>,
    ) -> Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError> {
        self.admitted.lock().unwrap().push(candidate.clone());
        self.result.lock().unwrap().take().unwrap()
    }
}

fn now() -> DateTime<Utc> {
    DateTime::parse_from_rfc3339("2026-07-14T10:00:00Z")
        .unwrap()
        .with_timezone(&Utc)
}

fn scope() -> AutomationRuntimeScope {
    AutomationRuntimeScope {
        tenant_id: "tenant-1".into(),
        project_id: "project-1".into(),
    }
}

fn candidate() -> AutomationHitlResumeCandidate {
    AutomationHitlResumeCandidate {
        request_id: "request-1".into(),
        request_type: "permission".into(),
        tenant_id: "tenant-1".into(),
        project_id: "project-1".into(),
        conversation_id: "conversation-1".into(),
        run_id: "run-1".into(),
        job_id: "job-1".into(),
        runtime_revision: 7,
        checkpoint_session_id: "run-1".into(),
    }
}

fn coordinator(
    result: Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError>,
) -> (Arc<FakeStore>, CronHitlResumeCoordinator) {
    let store = Arc::new(FakeStore {
        candidates: Mutex::new(vec![candidate()]),
        admitted: Mutex::new(Vec::new()),
        result: Mutex::new(Some(result)),
    });
    (store.clone(), CronHitlResumeCoordinator::new(store))
}

#[tokio::test]
async fn coordinator_uses_one_atomic_admission_with_the_observed_run_revision() {
    let (store, coordinator) = coordinator(Ok(AutomationHitlAdmissionOutcome::Applied {
        runtime_revision: 8,
    }));
    let report = coordinator.drain_once(&scope(), 10, now()).await.unwrap();
    assert_eq!(store.admitted.lock().unwrap().as_slice(), &[candidate()]);
    assert_eq!(report.candidates, 1);
    assert_eq!(report.queued, 1);
    assert_eq!(report.lost_race, 0);
}

#[tokio::test]
async fn concurrent_resume_admission_loss_is_reported_without_error() {
    let (_, coordinator) = coordinator(Ok(AutomationHitlAdmissionOutcome::NotAdmitted));
    let report = coordinator.drain_once(&scope(), 10, now()).await.unwrap();
    assert_eq!(report.queued, 0);
    assert_eq!(report.lost_race, 1);
}

#[tokio::test]
async fn atomic_admission_failure_is_returned_without_a_fallback_checkpoint_write() {
    let (store, coordinator) = coordinator(Err(AutomationRuntimeRepositoryError::LeaseLost));
    assert_eq!(
        coordinator
            .drain_once(&scope(), 10, now())
            .await
            .unwrap_err(),
        AutomationRuntimeRepositoryError::LeaseLost
    );
    assert_eq!(store.admitted.lock().unwrap().len(), 1);
}

#[tokio::test]
async fn secret_foreign_or_unversioned_candidates_never_reach_admission() {
    let mut secret = candidate();
    secret.request_type = "env_var".into();
    let mut foreign = candidate();
    foreign.tenant_id = "other".into();
    let mut unversioned = candidate();
    unversioned.runtime_revision = 0;
    for invalid in [secret, foreign, unversioned] {
        let (store, coordinator) = coordinator(Ok(AutomationHitlAdmissionOutcome::NotAdmitted));
        *store.candidates.lock().unwrap() = vec![invalid];
        assert_eq!(
            coordinator
                .drain_once(&scope(), 10, now())
                .await
                .unwrap_err(),
            AutomationRuntimeRepositoryError::InvalidRunState
        );
        assert!(store.admitted.lock().unwrap().is_empty());
    }
}
