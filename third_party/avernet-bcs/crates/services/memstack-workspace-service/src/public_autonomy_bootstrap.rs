//! Application boundary for durable autonomous Workspace root bootstrap.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceAutonomyBootstrapClaim, WorkspaceAutonomyBootstrapFailureOutcome,
    WorkspaceAutonomyBootstrapStore, WorkspaceAutonomyBootstrapStoreError,
};
use thiserror::Error;

/// Public projection of one fenced autonomous bootstrap lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyBootstrapClaim {
    pub bootstrap_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub objective_title: String,
    pub objective_description: Option<String>,
    pub attempt_count: i64,
    store_claim: WorkspaceAutonomyBootstrapClaim,
}

/// Result of releasing one failed autonomous bootstrap claim.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicWorkspaceAutonomyBootstrapFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Stable public autonomous bootstrap queue failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspaceAutonomyBootstrapError {
    #[error(transparent)]
    Store(#[from] WorkspaceAutonomyBootstrapStoreError),
}

/// Durable autonomous bootstrap claim, ACK, and failure use cases.
pub struct PublicWorkspaceAutonomyBootstrapService<'a> {
    store: WorkspaceAutonomyBootstrapStore<'a>,
}

impl<'a> PublicWorkspaceAutonomyBootstrapService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceAutonomyBootstrapStore::new(db, flavor),
        }
    }

    /// Lease a bounded batch of ready bootstrap requests.
    pub async fn claim_bootstraps(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceAutonomyBootstrapClaim>, PublicWorkspaceAutonomyBootstrapError>
    {
        Ok(self
            .store
            .claim(worker_id, now_ms, lease_expires_at_ms, limit)
            .await?
            .into_iter()
            .map(public_claim)
            .collect())
    }

    /// ACK the exact fenced claim with its durable Objective and root Task.
    pub async fn complete_bootstrap(
        &self,
        claim: &PublicWorkspaceAutonomyBootstrapClaim,
        objective_id: &str,
        root_task_id: &str,
        completed_at_ms: i64,
    ) -> Result<(), PublicWorkspaceAutonomyBootstrapError> {
        self.store
            .complete(
                &claim.store_claim,
                objective_id,
                root_task_id,
                completed_at_ms,
            )
            .await?;
        Ok(())
    }

    /// Release a failed claim for retry or dead-lettering.
    pub async fn fail_bootstrap(
        &self,
        claim: &PublicWorkspaceAutonomyBootstrapClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<PublicWorkspaceAutonomyBootstrapFailureOutcome, PublicWorkspaceAutonomyBootstrapError>
    {
        let WorkspaceAutonomyBootstrapFailureOutcome {
            attempt_count,
            dead_lettered,
        } = self
            .store
            .fail(&claim.store_claim, next_attempt_at_ms, last_error)
            .await?;
        Ok(PublicWorkspaceAutonomyBootstrapFailureOutcome {
            attempt_count,
            dead_lettered,
        })
    }
}

fn public_claim(claim: WorkspaceAutonomyBootstrapClaim) -> PublicWorkspaceAutonomyBootstrapClaim {
    PublicWorkspaceAutonomyBootstrapClaim {
        bootstrap_id: claim.bootstrap_id.clone(),
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        actor_id: claim.actor_id.clone(),
        objective_title: claim.objective_title.clone(),
        objective_description: claim.objective_description.clone(),
        attempt_count: claim.attempt_count,
        store_claim: claim,
    }
}
