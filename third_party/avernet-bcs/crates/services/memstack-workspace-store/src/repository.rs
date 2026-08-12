//! Execution and replay semantics for Workspace mutation plans.

use bcs_db_api::{DbError, DbPlugin, DbRow, DbTransactionStepResult};
use memstack_workspace_service_api::WorkspaceMutationCommand;
use serde_json::Value;
use thiserror::Error;

use crate::{WorkspaceCreationPlan, WorkspaceMutationPlan};

/// A committed or replayed Workspace mutation receipt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMutationOutcome {
    pub receipt_id: String,
    pub committed_revision: u64,
    pub response: Value,
    pub replayed: bool,
}

/// Mutation transaction or replay failure.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceMutationStoreError {
    #[error("Workspace mutation access denied")]
    AccessDenied,

    #[error("Workspace authority revision conflict")]
    RevisionConflict,

    #[error("Workspace domain mutation did not satisfy its row-count contract")]
    DomainConflict,

    #[error("Workspace already exists")]
    WorkspaceAlreadyExists,

    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,

    #[error("mutation receipt exists but has not been finalized")]
    IncompleteReceipt,

    #[error("mutation receipt is missing required data: {0}")]
    InvalidReceipt(&'static str),

    #[error("mutation receipt response is invalid JSON: {0}")]
    InvalidResponseJson(#[source] serde_json::Error),

    #[error(transparent)]
    Database(#[from] DbError),
}

/// Executes atomic Workspace mutation plans against a configured database.
pub struct WorkspaceMutationStore<'a> {
    db: &'a dyn DbPlugin,
}

impl<'a> WorkspaceMutationStore<'a> {
    /// Bind the store to one logical PostgreSQL or SQLite datasource.
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin) -> Self {
        Self { db }
    }

    /// Return a committed idempotent result before preparing destructive domain writes.
    ///
    /// # Errors
    ///
    /// Returns a receipt decoding or request-hash conflict error.
    pub async fn replay_committed(
        &self,
        command: &WorkspaceMutationCommand,
        receipt_lookup: &bcs_db_api::DbStatement,
    ) -> Result<Option<WorkspaceMutationOutcome>, WorkspaceMutationStoreError> {
        self.read_receipt_statement(command, receipt_lookup, true)
            .await
    }

    /// Execute once or replay a previously committed idempotent result.
    ///
    /// # Errors
    ///
    /// Returns a structured conflict for access, revision, domain row count,
    /// or request-hash mismatch; backend and receipt decoding failures are
    /// preserved separately.
    pub async fn execute(
        &self,
        command: &WorkspaceMutationCommand,
        plan: WorkspaceMutationPlan,
    ) -> Result<WorkspaceMutationOutcome, WorkspaceMutationStoreError> {
        if let Some(outcome) = self.read_receipt(command, &plan, true).await? {
            return Ok(outcome);
        }

        let transaction_result = self.db.transaction(plan.clone().into_steps()).await;
        let results = match transaction_result {
            Ok(results) => results,
            Err(error) => {
                if (is_receipt_race(&error, &plan) || error.is_duplicate_key())
                    && let Some(outcome) = self.read_receipt(command, &plan, true).await?
                {
                    return Ok(outcome);
                }
                return Err(classify_transaction_error(error, &plan));
            }
        };

        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceMutationStoreError::InvalidReceipt(
                "final transaction result is not a receipt query",
            ));
        };
        let Some(row) = rows.first() else {
            return Err(WorkspaceMutationStoreError::InvalidReceipt(
                "final receipt query returned no row",
            ));
        };
        receipt_outcome(command, row, false)?.ok_or(WorkspaceMutationStoreError::InvalidReceipt(
            "committed receipt is incomplete",
        ))
    }

    /// Create a new Workspace atomically or replay its committed receipt.
    ///
    /// # Errors
    ///
    /// Returns a structured conflict for missing project access, an existing
    /// Workspace, domain row-count failure, or idempotency hash mismatch.
    pub async fn execute_creation(
        &self,
        command: &WorkspaceMutationCommand,
        plan: WorkspaceCreationPlan,
    ) -> Result<WorkspaceMutationOutcome, WorkspaceMutationStoreError> {
        if let Some(outcome) = self
            .read_receipt_statement(command, plan.receipt_lookup(), true)
            .await?
        {
            return Ok(outcome);
        }

        let transaction_result = self.db.transaction(plan.clone().into_steps()).await;
        let results = match transaction_result {
            Ok(results) => results,
            Err(error) => {
                if (is_creation_receipt_race(&error, &plan) || error.is_duplicate_key())
                    && let Some(outcome) = self
                        .read_receipt_statement(command, plan.receipt_lookup(), true)
                        .await?
                {
                    return Ok(outcome);
                }
                return Err(classify_creation_error(error, &plan));
            }
        };

        outcome_from_transaction(command, &results)
    }

    async fn read_receipt(
        &self,
        command: &WorkspaceMutationCommand,
        plan: &WorkspaceMutationPlan,
        replayed: bool,
    ) -> Result<Option<WorkspaceMutationOutcome>, WorkspaceMutationStoreError> {
        self.read_receipt_statement(command, plan.receipt_lookup(), replayed)
            .await
    }

    async fn read_receipt_statement(
        &self,
        command: &WorkspaceMutationCommand,
        receipt_lookup: &bcs_db_api::DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceMutationOutcome>, WorkspaceMutationStoreError> {
        let rows = self.db.query(receipt_lookup.clone()).await?;
        let Some(row) = rows.first() else {
            return Ok(None);
        };
        receipt_outcome(command, row, replayed)
    }
}

fn outcome_from_transaction(
    command: &WorkspaceMutationCommand,
    results: &[DbTransactionStepResult],
) -> Result<WorkspaceMutationOutcome, WorkspaceMutationStoreError> {
    let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
        return Err(WorkspaceMutationStoreError::InvalidReceipt(
            "final transaction result is not a receipt query",
        ));
    };
    let Some(row) = rows.first() else {
        return Err(WorkspaceMutationStoreError::InvalidReceipt(
            "final receipt query returned no row",
        ));
    };
    receipt_outcome(command, row, false)?.ok_or(WorkspaceMutationStoreError::InvalidReceipt(
        "committed receipt is incomplete",
    ))
}

fn receipt_outcome(
    command: &WorkspaceMutationCommand,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceMutationOutcome>, WorkspaceMutationStoreError> {
    let request_hash = row
        .get_string("request_hash")?
        .ok_or(WorkspaceMutationStoreError::InvalidReceipt("request_hash"))?;
    if request_hash != command.request_hash().as_str() {
        return Err(WorkspaceMutationStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceMutationStoreError::IncompleteReceipt);
    };
    let committed_revision = u64::try_from(committed_revision)
        .map_err(|_| WorkspaceMutationStoreError::InvalidReceipt("committed_revision"))?;
    let response_json = row
        .get_string("response_json")?
        .ok_or(WorkspaceMutationStoreError::InvalidReceipt("response_json"))?;
    let response = serde_json::from_str(&response_json)
        .map_err(WorkspaceMutationStoreError::InvalidResponseJson)?;
    let receipt_id = row
        .get_string("receipt_id")?
        .ok_or(WorkspaceMutationStoreError::InvalidReceipt("receipt_id"))?;
    Ok(Some(WorkspaceMutationOutcome {
        receipt_id,
        committed_revision,
        response,
        replayed,
    }))
}

fn is_receipt_race(error: &DbError, plan: &WorkspaceMutationPlan) -> bool {
    matches!(
        error,
        DbError::TransactionExpectation { step_index, .. }
            if *step_index == plan.receipt_insert_step()
    )
}

fn is_creation_receipt_race(error: &DbError, plan: &WorkspaceCreationPlan) -> bool {
    matches!(
        error,
        DbError::TransactionExpectation { step_index, .. }
            if *step_index == plan.receipt_insert_step()
    )
}

fn classify_creation_error(
    error: DbError,
    plan: &WorkspaceCreationPlan,
) -> WorkspaceMutationStoreError {
    if error.is_duplicate_key() {
        return WorkspaceMutationStoreError::WorkspaceAlreadyExists;
    }
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        if *step_index == plan.access_step() {
            return WorkspaceMutationStoreError::AccessDenied;
        }
        if *step_index == plan.absence_step() {
            return WorkspaceMutationStoreError::WorkspaceAlreadyExists;
        }
        if plan.is_domain_step(*step_index) {
            return WorkspaceMutationStoreError::DomainConflict;
        }
    }
    WorkspaceMutationStoreError::Database(error)
}

fn classify_transaction_error(
    error: DbError,
    plan: &WorkspaceMutationPlan,
) -> WorkspaceMutationStoreError {
    if error.is_duplicate_key() {
        return WorkspaceMutationStoreError::DomainConflict;
    }
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        if *step_index == plan.access_step() {
            return WorkspaceMutationStoreError::AccessDenied;
        }
        if *step_index == plan.revision_check_step() || *step_index == plan.authority_cas_step() {
            return WorkspaceMutationStoreError::RevisionConflict;
        }
        if plan.is_domain_step(*step_index) {
            return WorkspaceMutationStoreError::DomainConflict;
        }
    }
    WorkspaceMutationStoreError::Database(error)
}
