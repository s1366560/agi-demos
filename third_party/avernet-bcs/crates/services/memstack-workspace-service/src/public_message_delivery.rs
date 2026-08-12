//! Durable Workspace message delivery recovery use cases.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use memstack_workspace_store::{WorkspaceMessageDeliveryClaim, WorkspaceMessageStore};

use crate::public_messages::{
    PublicWorkspaceMessage, PublicWorkspaceMessageDeliveryTarget, PublicWorkspaceMessageError,
    public_message,
};

/// Public projection of one fenced durable delivery lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PublicWorkspaceMessageDeliveryClaim {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub group_id: String,
    pub session_id: String,
    pub correlation_id: String,
    pub message: PublicWorkspaceMessage,
    pub target: PublicWorkspaceMessageDeliveryTarget,
    pub attempt_count: i64,
    pub worker_id: String,
    pub lease_expires_at_ms: i64,
    store_claim: WorkspaceMessageDeliveryClaim,
}

/// Result of releasing one public delivery attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicWorkspaceMessageDeliveryFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Public use cases over the durable Workspace message delivery queue.
pub struct PublicWorkspaceMessageDeliveryService<'a> {
    store: WorkspaceMessageStore<'a>,
}

impl<'a> PublicWorkspaceMessageDeliveryService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspaceMessageStore::new(db, flavor),
        }
    }

    /// Atomically lease pending or expired deliveries for one worker.
    ///
    /// # Errors
    ///
    /// Returns stable message projection, input, or persistence errors.
    pub async fn claim_deliveries(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<PublicWorkspaceMessageDeliveryClaim>, PublicWorkspaceMessageError> {
        self.store
            .claim_deliveries(worker_id, now_ms, lease_expires_at_ms, limit)
            .await?
            .into_iter()
            .map(public_delivery_claim)
            .collect()
    }

    /// Complete one delivery while preserving the store-owned lease fence.
    ///
    /// # Errors
    ///
    /// Returns a stable persistence error when the lease was lost or completion fails.
    pub async fn complete_delivery(
        &self,
        claim: &PublicWorkspaceMessageDeliveryClaim,
        delivered_at_ms: i64,
    ) -> Result<(), PublicWorkspaceMessageError> {
        self.store
            .complete_delivery(&claim.store_claim, delivered_at_ms)
            .await?;
        Ok(())
    }

    /// Release one failed delivery for retry or durable dead-lettering.
    ///
    /// # Errors
    ///
    /// Returns a stable persistence error when the lease was lost or release fails.
    pub async fn fail_delivery(
        &self,
        claim: &PublicWorkspaceMessageDeliveryClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<PublicWorkspaceMessageDeliveryFailureOutcome, PublicWorkspaceMessageError> {
        let outcome = self
            .store
            .fail_delivery(&claim.store_claim, next_attempt_at_ms, last_error)
            .await?;
        Ok(PublicWorkspaceMessageDeliveryFailureOutcome {
            attempt_count: outcome.attempt_count,
            dead_lettered: outcome.dead_lettered,
        })
    }
}

fn public_delivery_claim(
    store_claim: WorkspaceMessageDeliveryClaim,
) -> Result<PublicWorkspaceMessageDeliveryClaim, PublicWorkspaceMessageError> {
    Ok(PublicWorkspaceMessageDeliveryClaim {
        tenant_id: store_claim.tenant_id.clone(),
        project_id: store_claim.project_id.clone(),
        workspace_id: store_claim.message.workspace_id.clone(),
        group_id: store_claim.group_id.clone(),
        session_id: store_claim.session_id.clone(),
        correlation_id: store_claim.correlation_id.clone(),
        message: public_message(store_claim.message.clone())?,
        target: PublicWorkspaceMessageDeliveryTarget {
            agent_id: store_claim.target.agent_id.clone(),
            bot_uuid: store_claim.target.bot_uuid.clone(),
            display_name: store_claim.target.display_name.clone(),
        },
        attempt_count: store_claim.attempt_count,
        worker_id: store_claim.worker_id.clone(),
        lease_expires_at_ms: store_claim.lease_expires_at_ms,
        store_claim,
    })
}
