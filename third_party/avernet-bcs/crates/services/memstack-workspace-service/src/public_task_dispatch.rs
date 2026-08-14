//! Application boundary for durable Workspace Task dispatch recovery.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{
    WorkspaceTaskDispatchClaim, WorkspaceTaskDispatchFailureOutcome, WorkspaceTaskStore,
};

use crate::PublicWorkspaceTaskError;

/// Public projection of one fenced Task dispatch lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceTaskDispatchClaim {
    pub dispatch_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub task_id: String,
    pub attempt_id: Option<String>,
    pub plan_id: Option<String>,
    pub plan_node_id: Option<String>,
    pub user_id: String,
    pub agent_id: String,
    pub workspace_agent_binding_id: String,
    pub bot_uuid: String,
    pub group_id: String,
    pub conversation_id: String,
    pub delivery_request_id: String,
    pub task_title: String,
    pub task_description: Option<String>,
    pub task_status: String,
    pub attempt_count: i64,
    store_claim: WorkspaceTaskDispatchClaim,
}

/// Result of releasing one failed Task dispatch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicWorkspaceTaskDispatchFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Durable Task dispatch claim, correlation, ACK, and failure use cases.
pub struct PublicWorkspaceTaskDispatchService<'a> {
    store: WorkspaceTaskStore<'a>,
}

impl<'a> PublicWorkspaceTaskDispatchService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceTaskStore::new(db, flavor),
        }
    }

    /// Lease a bounded batch of ready dispatches.
    pub async fn claim_dispatches(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceTaskDispatchClaim>, PublicWorkspaceTaskError> {
        Ok(self
            .store
            .claim_task_dispatches(worker_id, now_ms, lease_expires_at_ms, limit)
            .await?
            .into_iter()
            .map(public_claim)
            .collect())
    }

    /// Persist and verify the runtime correlation before Provider delivery.
    pub async fn prepare_correlation(
        &self,
        claim: &PublicWorkspaceTaskDispatchClaim,
    ) -> Result<(), PublicWorkspaceTaskError> {
        self.store
            .prepare_task_dispatch_correlation(&claim.store_claim)
            .await?;
        Ok(())
    }

    /// ACK the exact fenced claim.
    pub async fn complete_dispatch(
        &self,
        claim: &PublicWorkspaceTaskDispatchClaim,
        delivered_at_ms: i64,
    ) -> Result<(), PublicWorkspaceTaskError> {
        self.store
            .complete_task_dispatch(&claim.store_claim, delivered_at_ms)
            .await?;
        Ok(())
    }

    /// ACK an already-terminal Task without creating a Runtime correlation.
    pub async fn complete_terminal_dispatch(
        &self,
        claim: &PublicWorkspaceTaskDispatchClaim,
        delivered_at_ms: i64,
    ) -> Result<(), PublicWorkspaceTaskError> {
        self.store
            .complete_terminal_task_dispatch(&claim.store_claim, delivered_at_ms)
            .await?;
        Ok(())
    }

    /// Release a failed claim for retry or dead-lettering.
    pub async fn fail_dispatch(
        &self,
        claim: &PublicWorkspaceTaskDispatchClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<PublicWorkspaceTaskDispatchFailureOutcome, PublicWorkspaceTaskError> {
        let WorkspaceTaskDispatchFailureOutcome {
            attempt_count,
            dead_lettered,
        } = self
            .store
            .fail_task_dispatch(&claim.store_claim, next_attempt_at_ms, last_error)
            .await?;
        Ok(PublicWorkspaceTaskDispatchFailureOutcome {
            attempt_count,
            dead_lettered,
        })
    }
}

fn public_claim(claim: WorkspaceTaskDispatchClaim) -> PublicWorkspaceTaskDispatchClaim {
    PublicWorkspaceTaskDispatchClaim {
        dispatch_id: claim.dispatch_id.clone(),
        tenant_id: claim.tenant_id.clone(),
        project_id: claim.project_id.clone(),
        workspace_id: claim.workspace_id.clone(),
        task_id: claim.task_id.clone(),
        attempt_id: claim.attempt_id.clone(),
        plan_id: claim.plan_id.clone(),
        plan_node_id: claim.plan_node_id.clone(),
        user_id: claim.user_id.clone(),
        agent_id: claim.agent_id.clone(),
        workspace_agent_binding_id: claim.workspace_agent_binding_id.clone(),
        bot_uuid: claim.bot_uuid.clone(),
        group_id: claim.group_id.clone(),
        conversation_id: claim.conversation_id.clone(),
        delivery_request_id: claim.delivery_request_id.clone(),
        task_title: claim.task_title.clone(),
        task_description: claim.task_description.clone(),
        task_status: claim.task_status.clone(),
        attempt_count: claim.attempt_count,
        store_claim: claim,
    }
}
