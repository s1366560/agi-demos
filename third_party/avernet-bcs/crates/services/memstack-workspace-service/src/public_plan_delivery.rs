//! Typed use cases over the fenced Workspace Plan runtime outbox.

use bcs_db_api::{DbPlugin, DbSqlFlavor};
use chrono::{DateTime, SecondsFormat, Utc};
use memstack_workspace_service_api::{
    WorkspacePlanDispatchAction, WorkspacePlanDispatchContractError, WorkspacePlanDispatchReceipt,
    WorkspacePlanDispatchRequest,
};
use memstack_workspace_store::{
    WorkspacePlanDeliveryClaim, WorkspacePlanDeliveryCompletion,
    WorkspacePlanDeliveryFailureOutcome, WorkspacePlanDeliveryStore,
    WorkspacePlanDeliveryStoreError,
};
use thiserror::Error;
use uuid::Uuid;

/// Public projection of one fenced Plan runtime action.
#[derive(Debug, Clone, PartialEq)]
pub struct PublicWorkspacePlanDeliveryClaim {
    pub request: WorkspacePlanDispatchRequest,
    pub attempt_count: u32,
    pub max_attempts: u32,
    pub worker_id: String,
    pub lease_expires_at: String,
    pub group_id: String,
    store_claim: WorkspacePlanDeliveryClaim,
}

/// Result of releasing one failed public dispatch attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct PublicWorkspacePlanDeliveryFailureOutcome {
    pub attempt_count: u32,
    pub dead_lettered: bool,
}

/// Public Plan runtime delivery use cases.
pub struct PublicWorkspacePlanDeliveryService<'a> {
    store: WorkspacePlanDeliveryStore<'a>,
}

impl<'a> PublicWorkspacePlanDeliveryService<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self {
            store: WorkspacePlanDeliveryStore::new(db, flavor),
        }
    }

    /// Atomically claim a bounded set of runtime-owned Plan events.
    ///
    /// # Errors
    ///
    /// Returns stable timestamp, contract, or persistence errors.
    pub async fn claim_deliveries(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<PublicWorkspacePlanDeliveryClaim>, PublicWorkspacePlanDeliveryError> {
        if now_ms < 0 || lease_expires_at_ms <= now_ms {
            return Err(PublicWorkspacePlanDeliveryError::InvalidTimestamp);
        }
        let now = timestamp(now_ms)?;
        let lease_expires_at = timestamp(lease_expires_at_ms)?;
        self.store
            .claim_deliveries(worker_id, &now, &lease_expires_at, limit)
            .await?
            .into_iter()
            .map(public_claim)
            .collect()
    }

    /// Persist Provider acceptance and the replayable runtime correlation first,
    /// then complete the exact outbox lease.
    ///
    /// # Errors
    ///
    /// Returns a contract, timestamp, correlation, lease, or database error.
    pub async fn complete_delivery(
        &self,
        claim: &PublicWorkspacePlanDeliveryClaim,
        receipt: &WorkspacePlanDispatchReceipt,
        accepted_at_ms: i64,
    ) -> Result<(), PublicWorkspacePlanDeliveryError> {
        let completion = WorkspacePlanDeliveryCompletion {
            correlation_id: claim.request.correlation_id().to_string(),
            conversation_id: claim.request.conversation_id().to_string(),
            provider_id: receipt.provider_id().to_string(),
            provider_bot_ref: receipt.provider_bot_ref().to_string(),
            provider_run_id: receipt.provider_run_id().to_string(),
            accepted_at: timestamp(accepted_at_ms)?,
        };
        self.store
            .complete_delivery(&claim.store_claim, &completion)
            .await?;
        Ok(())
    }

    /// Release one failed attempt for bounded retry or dead-lettering.
    ///
    /// # Errors
    ///
    /// Returns a timestamp, lease, or database error.
    pub async fn fail_delivery(
        &self,
        claim: &PublicWorkspacePlanDeliveryClaim,
        failed_at_ms: i64,
        next_attempt_at_ms: i64,
        stable_error: &str,
    ) -> Result<PublicWorkspacePlanDeliveryFailureOutcome, PublicWorkspacePlanDeliveryError> {
        let outcome: WorkspacePlanDeliveryFailureOutcome = self
            .store
            .fail_delivery(
                &claim.store_claim,
                &timestamp(failed_at_ms)?,
                &timestamp(next_attempt_at_ms)?,
                stable_error,
            )
            .await?;
        Ok(PublicWorkspacePlanDeliveryFailureOutcome {
            attempt_count: outcome.attempt_count,
            dead_lettered: outcome.dead_lettered,
        })
    }
}

/// Stable public delivery failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum PublicWorkspacePlanDeliveryError {
    #[error(transparent)]
    Store(#[from] WorkspacePlanDeliveryStoreError),
    #[error(transparent)]
    Contract(#[from] WorkspacePlanDispatchContractError),
    #[error("Workspace Plan delivery timestamp is invalid")]
    InvalidTimestamp,
    #[error("Workspace Plan runtime event type is unsupported: {0}")]
    UnsupportedEventType(String),
}

fn public_claim(
    store_claim: WorkspacePlanDeliveryClaim,
) -> Result<PublicWorkspacePlanDeliveryClaim, PublicWorkspacePlanDeliveryError> {
    let action = action_from_event(&store_claim.event_type)?;
    let correlation_id = store_claim
        .correlation_id
        .clone()
        .unwrap_or_else(|| deterministic_id("plan-correlation", &store_claim.outbox_id));
    let conversation_id = deterministic_id(
        "plan-conversation",
        &format!("{}:{}", store_claim.workspace_id, store_claim.plan_id),
    );
    let request = WorkspacePlanDispatchRequest::new(
        store_claim.tenant_id.clone(),
        store_claim.project_id.clone(),
        store_claim.workspace_id.clone(),
        store_claim.plan_id.clone(),
        store_claim.plan_node_id.clone(),
        store_claim.task_id.clone(),
        store_claim.attempt_id.clone(),
        store_claim.agent_id.clone(),
        action,
        store_claim.outbox_id.clone(),
        correlation_id,
        conversation_id,
        store_claim.payload.clone(),
    )?;
    Ok(PublicWorkspacePlanDeliveryClaim {
        request,
        attempt_count: store_claim.attempt_count,
        max_attempts: store_claim.max_attempts,
        worker_id: store_claim.lease_owner.clone(),
        lease_expires_at: store_claim.lease_expires_at.clone(),
        group_id: store_claim.group_id.clone(),
        store_claim,
    })
}

fn action_from_event(
    event_type: &str,
) -> Result<WorkspacePlanDispatchAction, PublicWorkspacePlanDeliveryError> {
    match event_type {
        "operator_stale_attempt_recovery_requested" => {
            Ok(WorkspacePlanDispatchAction::RecoverStaleAttempts)
        }
        "operator_iteration_next_requested" => {
            Ok(WorkspacePlanDispatchAction::TriggerNextIteration)
        }
        "workspace_pipeline_run_requested" => Ok(WorkspacePlanDispatchAction::RunPipeline),
        "delivery_contract_regeneration_requested" => {
            Ok(WorkspacePlanDispatchAction::RegenerateDeliveryContract)
        }
        other => Err(PublicWorkspacePlanDeliveryError::UnsupportedEventType(
            other.to_string(),
        )),
    }
}

fn deterministic_id(namespace: &str, seed: &str) -> String {
    Uuid::new_v5(
        &Uuid::NAMESPACE_URL,
        format!("memstack:{namespace}:{seed}").as_bytes(),
    )
    .to_string()
}

fn timestamp(timestamp_ms: i64) -> Result<String, PublicWorkspacePlanDeliveryError> {
    DateTime::<Utc>::from_timestamp_millis(timestamp_ms)
        .map(|timestamp| timestamp.to_rfc3339_opts(SecondsFormat::Millis, true))
        .ok_or(PublicWorkspacePlanDeliveryError::InvalidTimestamp)
}
