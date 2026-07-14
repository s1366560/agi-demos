//! Crash-safe resume coordination for answered automation HITL requests.
//!
//! The ordering is deliberate: persist the answer in the ReAct checkpoint
//! first, then move the durable run back to `queued`. Replaying after a crash
//! between those steps is safe because checkpoint acceptance is idempotent and
//! the run transition is a fenced compare-and-set.

#![allow(dead_code)]

use std::sync::Arc;

use agistack_adapters_postgres::{
    AutomationHitlResumeCandidate, AutomationRuntimeRepositoryError, AutomationRuntimeScope,
    PgCronAutomationRuntimeRepository, PgHitlRequestRepository, PgPool,
};
use agistack_core::agent::{ReActEngine, SessionStatus};
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

    async fn queue_resume(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError>;
}

pub(crate) struct PgAutomationHitlResumeStore {
    hitl: PgHitlRequestRepository,
    runtime: PgCronAutomationRuntimeRepository,
}

impl PgAutomationHitlResumeStore {
    pub(crate) fn new(pool: PgPool) -> Self {
        Self {
            hitl: PgHitlRequestRepository::new(pool.clone()),
            runtime: PgCronAutomationRuntimeRepository::new(pool),
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

    async fn queue_resume(
        &self,
        candidate: &AutomationHitlResumeCandidate,
        observed_at: DateTime<Utc>,
    ) -> Result<bool, AutomationRuntimeRepositoryError> {
        self.runtime
            .queue_resume(
                &candidate.tenant_id,
                &candidate.project_id,
                &candidate.run_id,
                &candidate.conversation_id,
                observed_at,
            )
            .await
    }
}

#[async_trait]
pub(crate) trait CheckpointAnswerAcceptor: Send + Sync {
    async fn accept(&self, candidate: &AutomationHitlResumeCandidate) -> CoreResult<()>;
}

#[async_trait]
impl CheckpointAnswerAcceptor for ReActEngine {
    async fn accept(&self, candidate: &AutomationHitlResumeCandidate) -> CoreResult<()> {
        let state = self
            .accept_human_response(
                &candidate.checkpoint_session_id,
                &candidate.request_id,
                &candidate.answer,
            )
            .await?;
        if state.status != SessionStatus::Running {
            return Err(CoreError::Tool(
                "automation checkpoint is not resumable".to_string(),
            ));
        }
        Ok(())
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
    checkpoints: Arc<dyn CheckpointAnswerAcceptor>,
}

impl CronHitlResumeCoordinator {
    pub(crate) fn new(
        store: Arc<dyn AutomationHitlResumeStore>,
        checkpoints: Arc<dyn CheckpointAnswerAcceptor>,
    ) -> Self {
        Self { store, checkpoints }
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
            self.checkpoints
                .accept(&candidate)
                .await
                .map_err(map_checkpoint_error)?;
            if self.store.queue_resume(&candidate, now).await? {
                report.queued += 1;
            } else {
                report.lost_race += 1;
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

fn map_checkpoint_error(error: CoreError) -> AutomationRuntimeRepositoryError {
    match error {
        CoreError::NotFound => AutomationRuntimeRepositoryError::NotFound,
        CoreError::Tool(_) => AutomationRuntimeRepositoryError::InvalidRunState,
        _ => AutomationRuntimeRepositoryError::Storage(
            "persist automation HITL checkpoint answer failed".to_string(),
        ),
    }
}

#[cfg(test)]
mod tests;
