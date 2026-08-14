//! Application boundary for durable Workspace Autonomy continuation recovery.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceAutonomyProgressionClaim, WorkspaceAutonomyProgressionFailureOutcome,
    WorkspaceAutonomyProgressionStore, WorkspaceAutonomyProgressionStoreError,
};
use thiserror::Error;

/// Public projection of one fenced Autonomy progression lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyProgressionClaim {
    pub progression_id: String,
    pub tick_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub root_task_id: String,
    pub actor_id: String,
    pub judge_agent_id: String,
    pub workspace_agent_binding_id: String,
    pub task_title: String,
    pub task_description: String,
    pub attempt_count: i64,
    store_claim: WorkspaceAutonomyProgressionClaim,
}

/// Result of releasing one failed Autonomy progression.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyProgressionFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Stable public Autonomy progression queue failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyProgressionError {
    #[error(transparent)]
    Store(#[from] WorkspaceAutonomyProgressionStoreError),
}

/// Durable Autonomy progression claim, ACK, and failure use cases.
pub struct PublicWorkspaceAutonomyProgressionService<'a> {
    store: WorkspaceAutonomyProgressionStore<'a>,
}

impl<'a> PublicWorkspaceAutonomyProgressionService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceAutonomyProgressionStore::new(db, flavor),
        }
    }

    /// Lease a bounded batch of ready continuations.
    pub async fn claim_progressions(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceAutonomyProgressionClaim>, PublicWorkspaceAutonomyProgressionError>
    {
        Ok(self
            .store
            .claim(worker_id, now_ms, lease_expires_at_ms, limit)
            .await?
            .into_iter()
            .map(public_claim)
            .collect())
    }

    /// ACK the exact fenced claim with its durable execution Task.
    pub async fn complete_progression(
        &self,
        claim: &PublicWorkspaceAutonomyProgressionClaim,
        execution_task_id: &str,
        completed_at_ms: i64,
    ) -> Result<(), PublicWorkspaceAutonomyProgressionError> {
        self.store
            .complete(&claim.store_claim, execution_task_id, completed_at_ms)
            .await?;
        Ok(())
    }

    /// Release a failed claim for retry or dead-lettering.
    pub async fn fail_progression(
        &self,
        claim: &PublicWorkspaceAutonomyProgressionClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<
        PublicWorkspaceAutonomyProgressionFailureOutcome,
        PublicWorkspaceAutonomyProgressionError,
    > {
        let WorkspaceAutonomyProgressionFailureOutcome {
            attempt_count,
            dead_lettered,
        } = self
            .store
            .fail(&claim.store_claim, next_attempt_at_ms, last_error)
            .await?;
        Ok(PublicWorkspaceAutonomyProgressionFailureOutcome {
            attempt_count,
            dead_lettered,
        })
    }
}

fn public_claim(
    claim: WorkspaceAutonomyProgressionClaim,
) -> PublicWorkspaceAutonomyProgressionClaim {
    PublicWorkspaceAutonomyProgressionClaim {
        progression_id: claim.progression_id.clone(),
        tick_id: claim.tick_id.clone(),
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        root_task_id: claim.root_task_id.clone(),
        actor_id: claim.actor_id.clone(),
        judge_agent_id: claim.judge_agent_id.clone(),
        workspace_agent_binding_id: claim.workspace_agent_binding_id.clone(),
        task_title: claim.task_title.clone(),
        task_description: claim.task_description.clone(),
        attempt_count: claim.attempt_count,
        store_claim: claim,
    }
}
