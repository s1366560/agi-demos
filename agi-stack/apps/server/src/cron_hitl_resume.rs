//! Resume coordination through one atomic, revision-fenced database admission.

#![allow(dead_code)]

use std::sync::Arc;

use agistack_adapters_postgres::{
    AutomationHitlAdmissionCommand, AutomationHitlAdmissionOutcome, AutomationHitlResumeCandidate,
    AutomationRuntimeRepositoryError, AutomationRuntimeScope, PgAutomationHitlAdmission,
    PgHitlRequestRepository, PgPool,
};
use agistack_core::ports::{CoreError, CoreResult};
use async_trait::async_trait;
use chrono::{DateTime, Utc};

#[async_trait]
pub(crate) trait AutomationHitlResumeStore: Send + Sync {
    async fn list_candidates(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<AutomationHitlResumeCandidate>>;

    async fn admit_answer(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        observed_at: DateTime<Utc>,
    ) -> Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError>;
}

pub(crate) struct PgAutomationHitlResumeStore {
    hitl: PgHitlRequestRepository,
    admission: PgAutomationHitlAdmission,
}

impl PgAutomationHitlResumeStore {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self {
            hitl: PgHitlRequestRepository::new(pool.clone()),
            admission: PgAutomationHitlAdmission::new(pool),
        }
    }
}

#[async_trait]
impl AutomationHitlResumeStore for PgAutomationHitlResumeStore {
    async fn list_candidates(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> CoreResult<Vec<AutomationHitlResumeCandidate>> {
        self.hitl
            .list_automation_resume_candidates(&scope.tenant_id, &scope.project_id, limit, now)
            .await
    }

    async fn admit_answer(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        observed_at: DateTime<Utc>,
    ) -> Result<AutomationHitlAdmissionOutcome, AutomationRuntimeRepositoryError> {
        self.admission
            .admit(
                &AutomationHitlAdmissionCommand {
                    tenant_id: candidate.tenant_id.clone(),
                    project_id: candidate.project_id.clone(),
                    job_id: candidate.job_id.clone(),
                    run_id: candidate.run_id.clone(),
                    conversation_id: candidate.conversation_id.clone(),
                    request_id: candidate.request_id.clone(),
                    expected_runtime_revision: candidate.runtime_revision,
                },
                observed_at,
            )
            .await
    }
}

#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub(crate) struct AutomationHitlResumeReport {
    pub(crate) candidates: usize,
    pub(crate) queued: usize,
    pub(crate) lost_race: usize,
}

pub(crate) struct CronHitlResumeCoordinator {
    store: Arc<dyn AutomationHitlResumeStore>,
}

impl CronHitlResumeCoordinator {
    pub(crate) fn new(store: Arc<dyn AutomationHitlResumeStore>) -> Self {
        Self { store }
    }

    pub(crate) async fn drain_once(
        &self,
        scope: &AutomationRuntimeScope,
        limit: i64,
        now: DateTime<Utc>,
    ) -> Result<AutomationHitlResumeReport, AutomationRuntimeRepositoryError> {
        let candidates = self
            .store
            .list_candidates(scope, limit, now)
            .await
            .map_err(redacted_storage_error)?;
        let mut report = AutomationHitlResumeReport {
            candidates: candidates.len(),
            ..Default::default()
        };

        for candidate in candidates {
            validate_candidate(scope, &candidate)?;
            match self.store.admit_answer(&candidate, now).await? {
                AutomationHitlAdmissionOutcome::Applied { .. } => report.queued += 1,
                AutomationHitlAdmissionOutcome::NotAdmitted => report.lost_race += 1,
            }
        }

        Ok(report)
    }
}

fn validate_candidate(
    scope: &AutomationRuntimeScope,
    candidate: &AutomationHitlResumeCandidate,
) -> Result<(), AutomationRuntimeRepositoryError> {
    let supported_type = matches!(
        candidate.request_type.as_str(),
        "clarification" | "decision" | "permission"
    );
    if !supported_type
        || candidate.tenant_id != scope.tenant_id
        || candidate.project_id != scope.project_id
        || candidate.checkpoint_session_id != candidate.run_id
        || candidate.runtime_revision <= 0
        || candidate.job_id.trim().is_empty()
    {
        return Err(AutomationRuntimeRepositoryError::InvalidRunState);
    }
    Ok(())
}

fn redacted_storage_error(_error: CoreError) -> AutomationRuntimeRepositoryError {
    AutomationRuntimeRepositoryError::Storage(
        "list answered automation HITL requests failed".to_string(),
    )
}

#[cfg(test)]
mod tests;
