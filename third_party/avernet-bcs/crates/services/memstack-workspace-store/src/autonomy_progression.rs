//! Durable, fenced delivery queue for Agent-judged Workspace Autonomy continuations.

use bcs_db_api::{
    DbError, DbExecuteResult, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
};
use thiserror::Error;

const MAX_PROGRESSION_CLAIM_LIMIT: i64 = 100;
const MAX_LAST_ERROR_CHARS: usize = 128;

/// One currently owned Autonomy progression lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyProgressionClaim {
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
    pub worker_id: String,
    pub lease_expires_at_ms: i64,
    pub lease_generation: i64,
}

/// Failed-attempt release result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkspaceAutonomyProgressionFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Stable Autonomy progression queue failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyProgressionStoreError {
    #[error("invalid Workspace Autonomy progression claim")]
    InvalidClaim,
    #[error("Workspace Autonomy progression lease was lost")]
    LeaseLost,
    #[error("persisted Workspace Autonomy progression record is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite Autonomy progression queue repository.
pub struct WorkspaceAutonomyProgressionStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyProgressionStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Lease pending or expired continuations with a monotonic fencing generation.
    pub async fn claim(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<WorkspaceAutonomyProgressionClaim>, WorkspaceAutonomyProgressionStoreError>
    {
        validate_claim(worker_id, now_ms, lease_expires_at_ms, limit)?;
        self.db
            .execute(reap_exhausted_statement(self.flavor, now_ms))
            .await?;
        let rows = self
            .db
            .query(claim_statement(
                self.flavor,
                worker_id,
                now_ms,
                lease_expires_at_ms,
                limit,
            ))
            .await?;
        rows.iter()
            .map(|row| progression_claim_from_row(row, worker_id, lease_expires_at_ms))
            .collect()
    }

    /// ACK the exact fenced claim after its execution Task is durably dispatched.
    pub async fn complete(
        &self,
        claim: &WorkspaceAutonomyProgressionClaim,
        execution_task_id: &str,
        completed_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyProgressionStoreError> {
        if execution_task_id.trim().is_empty()
            || execution_task_id.chars().count() > 128
            || completed_at_ms < 0
        {
            return Err(WorkspaceAutonomyProgressionStoreError::InvalidClaim);
        }
        let result = self
            .db
            .execute(complete_statement(
                self.flavor,
                claim,
                execution_task_id,
                completed_at_ms,
            ))
            .await?;
        require_owned_lease(result)
    }

    /// Release a failed claim for bounded retry or durable dead-lettering.
    pub async fn fail(
        &self,
        claim: &WorkspaceAutonomyProgressionClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<WorkspaceAutonomyProgressionFailureOutcome, WorkspaceAutonomyProgressionStoreError>
    {
        if next_attempt_at_ms < 0
            || last_error.trim().is_empty()
            || last_error.chars().count() > MAX_LAST_ERROR_CHARS
        {
            return Err(WorkspaceAutonomyProgressionStoreError::InvalidClaim);
        }
        let rows = self
            .db
            .query(fail_statement(
                self.flavor,
                claim,
                next_attempt_at_ms,
                last_error,
            ))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceAutonomyProgressionStoreError::LeaseLost);
        };
        Ok(WorkspaceAutonomyProgressionFailureOutcome {
            attempt_count: required_i64(row, "attempt_count")?,
            dead_lettered: required_string(row, "status")? == "dead_letter",
        })
    }
}

fn validate_claim(
    worker_id: &str,
    now_ms: i64,
    lease_expires_at_ms: i64,
    limit: i64,
) -> Result<(), WorkspaceAutonomyProgressionStoreError> {
    if worker_id.trim().is_empty()
        || worker_id.chars().count() > 191
        || now_ms < 0
        || lease_expires_at_ms <= now_ms
        || !(1..=MAX_PROGRESSION_CLAIM_LIMIT).contains(&limit)
    {
        return Err(WorkspaceAutonomyProgressionStoreError::InvalidClaim);
    }
    Ok(())
}

fn claim_statement(
    flavor: DbSqlFlavor,
    worker_id: &str,
    now_ms: i64,
    lease_expires_at_ms: i64,
    limit: i64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_progression_outbox SET status = 'processing', \
             attempt_count = attempt_count + 1, lease_generation = lease_generation + 1, \
             lease_owner = ",
        )
        .bind(worker_id)
        .push_static(", lease_expires_at_ms = ")
        .bind(lease_expires_at_ms)
        .push_static(" WHERE ");
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static(
                "progression_id IN (SELECT progression_id FROM \
                 workspace_autonomy_progression_outbox WHERE attempt_count < max_attempts \
                 AND ((status = 'pending' AND next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(")) ORDER BY created_at_ms ASC, progression_id ASC LIMIT ")
            .bind(limit)
            .push_static(" FOR UPDATE SKIP LOCKED)"),
        DbSqlFlavor::Sqlite => builder
            .push_static(
                "rowid IN (SELECT rowid FROM workspace_autonomy_progression_outbox WHERE \
                 attempt_count < max_attempts AND ((status = 'pending' AND \
                 next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(") ) ORDER BY created_at_ms ASC, progression_id ASC LIMIT ")
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(
            " RETURNING progression_id, tick_id, tenant_id, project_id, workspace_id, \
             root_task_id, actor_id, judge_agent_id, workspace_agent_binding_id, task_title, \
             task_description, attempt_count, lease_generation",
        )
        .build()
}

fn reap_exhausted_statement(flavor: DbSqlFlavor, now_ms: i64) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_progression_outbox SET status = 'dead_letter', \
             lease_owner = NULL, lease_expires_at_ms = NULL, last_error = \
             COALESCE(last_error, 'autonomy progression lease expired after maximum attempts') \
             WHERE attempt_count >= max_attempts AND ((status = 'pending' AND \
             next_attempt_at_ms <= ",
        )
        .bind(now_ms)
        .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
        .bind(now_ms)
        .push_static("))")
        .build()
}

fn complete_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceAutonomyProgressionClaim,
    execution_task_id: &str,
    completed_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_progression_outbox SET status = 'completed', \
             execution_task_id = ",
        )
        .bind(execution_task_id)
        .push_static(", completed_at_ms = ")
        .bind(completed_at_ms)
        .push_static(
            ", lease_owner = NULL, lease_expires_at_ms = NULL, last_error = NULL WHERE \
             progression_id = ",
        )
        .bind(claim.progression_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(claim.worker_id.as_str())
        .push_static(" AND lease_expires_at_ms = ")
        .bind(claim.lease_expires_at_ms)
        .push_static(" AND lease_generation = ")
        .bind(claim.lease_generation)
        .build()
}

fn fail_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceAutonomyProgressionClaim,
    next_attempt_at_ms: i64,
    last_error: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_progression_outbox SET status = CASE WHEN \
             attempt_count >= max_attempts THEN 'dead_letter' ELSE 'pending' END, \
             next_attempt_at_ms = ",
        )
        .bind(next_attempt_at_ms)
        .push_static(", last_error = ")
        .bind(last_error)
        .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL WHERE progression_id = ")
        .bind(claim.progression_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(claim.worker_id.as_str())
        .push_static(" AND lease_expires_at_ms = ")
        .bind(claim.lease_expires_at_ms)
        .push_static(" AND lease_generation = ")
        .bind(claim.lease_generation)
        .push_static(" RETURNING status, attempt_count")
        .build()
}

fn progression_claim_from_row(
    row: &DbRow,
    worker_id: &str,
    lease_expires_at_ms: i64,
) -> Result<WorkspaceAutonomyProgressionClaim, WorkspaceAutonomyProgressionStoreError> {
    Ok(WorkspaceAutonomyProgressionClaim {
        progression_id: required_string(row, "progression_id")?,
        tick_id: required_string(row, "tick_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        root_task_id: required_string(row, "root_task_id")?,
        actor_id: required_string(row, "actor_id")?,
        judge_agent_id: required_string(row, "judge_agent_id")?,
        workspace_agent_binding_id: required_string(row, "workspace_agent_binding_id")?,
        task_title: required_string(row, "task_title")?,
        task_description: required_string(row, "task_description")?,
        attempt_count: required_i64(row, "attempt_count")?,
        worker_id: worker_id.to_string(),
        lease_expires_at_ms,
        lease_generation: required_i64(row, "lease_generation")?,
    })
}

fn require_owned_lease(
    result: DbExecuteResult,
) -> Result<(), WorkspaceAutonomyProgressionStoreError> {
    if result.affected_rows == 1 {
        Ok(())
    } else {
        Err(WorkspaceAutonomyProgressionStoreError::LeaseLost)
    }
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyProgressionStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAutonomyProgressionStoreError::InvalidRecord(
            column,
        ))
}

fn required_i64(
    row: &DbRow,
    column: &'static str,
) -> Result<i64, WorkspaceAutonomyProgressionStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceAutonomyProgressionStoreError::InvalidRecord(
            column,
        ))
}

#[cfg(test)]
#[path = "autonomy_progression_sql_tests.rs"]
mod sql_tests;
