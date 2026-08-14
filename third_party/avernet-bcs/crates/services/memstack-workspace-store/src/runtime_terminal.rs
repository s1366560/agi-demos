//! Atomic Runtime terminal, execution Task, and attempt convergence.

use bcs_db_api::{DbCountExpectation, DbError, DbPlugin, DbSqlFlavor, DbTransactionStep};
use serde_json::{Value, json};
use thiserror::Error;

mod sql;

use self::sql::{
    RuntimeCorrelation, RuntimeOutboxInsert, affected_rows, attempt_terminal_update,
    authority_revision_update, correlation_from_row, correlation_select,
    correlation_terminal_update, ensure_write_hash, outbox_insert, outcome_from_row,
    plan_event_insert, provider_event_hash_bind, provider_event_ingested_update,
    provider_terminal_select, task_terminal_update, terminal_insert, terminal_payload,
    terminal_read_select, terminal_result_select, transaction_row,
};

/// Tenant, Project, and Workspace boundary for one Runtime terminal.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceRuntimeTerminalScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical terminal content prepared by the application service.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceRuntimeTerminalWrite {
    pub execution_status: String,
    pub terminal_message_id: String,
    pub terminal_event_id: String,
    pub report: Value,
    pub report_hash: String,
    pub failure_reason: Option<String>,
}

/// Durable terminal proof plus the structurally converged Task state.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceRuntimeTerminalOutcome {
    pub correlation_id: String,
    pub provider_run_id: String,
    pub delivery_request_id: String,
    pub status: String,
    pub outbox_id: String,
    pub terminal_id: Option<String>,
    pub terminal_message_id: String,
    pub terminal_event_id: String,
    pub report: Value,
    pub report_hash: String,
    pub task_status: Option<String>,
    pub attempt_status: Option<String>,
    pub provider_event_hash: Option<String>,
    pub provider_event_ingested: bool,
    pub created: bool,
}

/// Stable Runtime terminal persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceRuntimeTerminalStoreError {
    #[error("Runtime correlation was not found")]
    NotFound,
    #[error("Runtime terminal conflicts with the persisted terminal")]
    Conflict,
    #[error("persisted Runtime terminal record is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error("persisted Runtime terminal JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite repository for terminal convergence authority.
pub struct WorkspaceRuntimeTerminalStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceRuntimeTerminalStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Atomically persist the terminal and converge its Task and attempt.
    pub async fn record(
        &self,
        scope: &WorkspaceRuntimeTerminalScope,
        correlation_id: &str,
        write: &WorkspaceRuntimeTerminalWrite,
    ) -> Result<WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalStoreError> {
        let correlation = self
            .correlation_by_id(scope, correlation_id)
            .await?
            .ok_or(WorkspaceRuntimeTerminalStoreError::NotFound)?;
        ensure_write_hash(write)?;

        let terminal_id = format!("runtime-terminal-{correlation_id}");
        let outbox_id = format!("runtime-outbox-{correlation_id}");
        let plan_event_id = format!("runtime-plan-event-{correlation_id}");
        let idempotency_key = format!("runtime-terminal:{correlation_id}");
        let payload = terminal_payload(&correlation, write);
        let payload_json = serde_json::to_string(&payload)
            .map_err(WorkspaceRuntimeTerminalStoreError::InvalidJson)?;
        let metadata_json = json!({"report_hash": &write.report_hash}).to_string();

        let mut steps = vec![DbTransactionStep::Execute(authority_revision_update(
            self.flavor,
            &correlation,
            &idempotency_key,
        ))];
        if let Some(task_id) = correlation.task_id.as_deref() {
            steps.push(DbTransactionStep::ExecuteChecked {
                statement: task_terminal_update(
                    self.flavor,
                    &correlation,
                    task_id,
                    &idempotency_key,
                    write,
                ),
                expected_affected_rows: DbCountExpectation::exactly(1),
            });
        }
        if let Some(attempt_id) = correlation.attempt_id.as_deref() {
            steps.push(DbTransactionStep::ExecuteChecked {
                statement: attempt_terminal_update(
                    self.flavor,
                    &correlation,
                    attempt_id,
                    &idempotency_key,
                    write,
                ),
                expected_affected_rows: DbCountExpectation::exactly(1),
            });
        }
        if correlation.plan_id.is_some() {
            steps.push(DbTransactionStep::Execute(plan_event_insert(
                self.flavor,
                &correlation,
                &plan_event_id,
                &payload_json,
                &idempotency_key,
            )));
        }
        steps.push(DbTransactionStep::Execute(outbox_insert(
            self.flavor,
            RuntimeOutboxInsert::new(
                &correlation,
                &outbox_id,
                &idempotency_key,
                write.execution_status.as_str(),
                &payload_json,
                &metadata_json,
            ),
        )?));
        if correlation.plan_id.is_some() {
            steps.push(DbTransactionStep::Execute(terminal_insert(
                self.flavor,
                &correlation,
                &terminal_id,
                &plan_event_id,
                &outbox_id,
                write,
            )));
        }
        steps.push(DbTransactionStep::ExecuteChecked {
            statement: correlation_terminal_update(
                self.flavor,
                correlation_id,
                write.execution_status.as_str(),
            ),
            expected_affected_rows: DbCountExpectation::exactly(1),
        });
        let result_index = steps.len();
        steps.push(DbTransactionStep::QueryChecked {
            statement: terminal_result_select(
                self.flavor,
                "c.correlation_id",
                correlation_id,
                &idempotency_key,
            ),
            expected_rows: DbCountExpectation::exactly(1),
        });

        let results = self.db.transaction(steps).await.map_err(|error| {
            if matches!(error, DbError::TransactionExpectation { .. }) {
                WorkspaceRuntimeTerminalStoreError::Conflict
            } else {
                error.into()
            }
        })?;
        let created = affected_rows(&results, 0)? > 0;
        let row = transaction_row(&results, result_index)?.ok_or(
            WorkspaceRuntimeTerminalStoreError::InvalidRecord("terminal result"),
        )?;
        outcome_from_row(row, Some(write), created)
    }

    /// Read a scoped terminal proof by correlation id.
    pub async fn read(
        &self,
        scope: &WorkspaceRuntimeTerminalScope,
        correlation_id: &str,
    ) -> Result<WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalStoreError> {
        let idempotency_key = format!("runtime-terminal:{correlation_id}");
        let rows = self
            .db
            .query(terminal_read_select(
                self.flavor,
                scope,
                correlation_id,
                &idempotency_key,
            ))
            .await?;
        let row = rows
            .first()
            .ok_or(WorkspaceRuntimeTerminalStoreError::NotFound)?;
        outcome_from_row(row, None, false)
    }

    /// Resolve and verify the persisted terminal addressed by Provider run id.
    pub async fn verify_provider_terminal(
        &self,
        provider_run_id: &str,
        expected_status: &str,
        expected_terminal_message_id: &str,
        expected_terminal_event_id: &str,
        expected_report: &Value,
        expected_event_hash: &str,
    ) -> Result<WorkspaceRuntimeTerminalOutcome, WorkspaceRuntimeTerminalStoreError> {
        let rows = self
            .db
            .query(provider_terminal_select(self.flavor, provider_run_id))
            .await?;
        let row = rows
            .first()
            .ok_or(WorkspaceRuntimeTerminalStoreError::NotFound)?;
        let mut outcome = outcome_from_row(row, None, false)?;
        if outcome.provider_run_id != provider_run_id
            || outcome.status != expected_status
            || outcome.terminal_message_id != expected_terminal_message_id
            || outcome.terminal_event_id != expected_terminal_event_id
            || outcome.report != *expected_report
            || outcome
                .provider_event_hash
                .as_deref()
                .is_some_and(|hash| hash != expected_event_hash)
        {
            return Err(WorkspaceRuntimeTerminalStoreError::Conflict);
        }
        let bound = self
            .db
            .execute(provider_event_hash_bind(
                self.flavor,
                provider_run_id,
                expected_status,
                expected_event_hash,
            ))
            .await?;
        if bound.affected_rows != 1 {
            return Err(WorkspaceRuntimeTerminalStoreError::Conflict);
        }
        outcome.provider_event_hash = Some(expected_event_hash.to_string());
        Ok(outcome)
    }

    /// Mark the exact verified Provider event as ingested by Message Flow.
    pub async fn mark_provider_event_ingested(
        &self,
        provider_run_id: &str,
        expected_event_hash: &str,
    ) -> Result<(), WorkspaceRuntimeTerminalStoreError> {
        let result = self
            .db
            .execute(provider_event_ingested_update(
                self.flavor,
                provider_run_id,
                expected_event_hash,
            ))
            .await?;
        if result.affected_rows == 1 {
            Ok(())
        } else {
            Err(WorkspaceRuntimeTerminalStoreError::Conflict)
        }
    }

    async fn correlation_by_id(
        &self,
        scope: &WorkspaceRuntimeTerminalScope,
        correlation_id: &str,
    ) -> Result<Option<RuntimeCorrelation>, WorkspaceRuntimeTerminalStoreError> {
        let rows = self
            .db
            .query(correlation_select(self.flavor, scope, correlation_id))
            .await?;
        rows.first().map(correlation_from_row).transpose()
    }
}
