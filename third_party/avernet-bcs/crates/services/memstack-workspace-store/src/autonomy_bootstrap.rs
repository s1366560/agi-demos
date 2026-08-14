//! Durable fenced queue for autonomous Workspace root bootstrapping.

use bcs_db_api::{
    DbCountExpectation, DbError, DbExecuteResult, DbPlugin, DbRow, DbSqlFlavor, DbStatement,
    DbStatementBuilder,
};
use thiserror::Error;

use crate::{WorkspaceDomainMutation, WorkspaceProfileSnapshot};

const MAX_BOOTSTRAP_CLAIM_LIMIT: i64 = 100;
const MAX_LAST_ERROR_CHARS: usize = 128;
const RECOVERY_BOOTSTRAP_PREFIX: &str = "autonomy-bootstrap-recovery:";

#[derive(Debug, Clone, Copy)]
struct WorkspaceAutonomyBootstrapEnsure<'a> {
    tenant_id: &'a str,
    project_id: &'a str,
    workspace_id: &'a str,
    actor_id: &'a str,
    objective_title: &'a str,
    objective_description: Option<&'a str>,
    created_at_ms: i64,
}

/// One currently owned autonomous bootstrap lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyBootstrapClaim {
    pub bootstrap_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub actor_id: String,
    pub objective_title: String,
    pub objective_description: Option<String>,
    pub attempt_count: i64,
    pub worker_id: String,
    pub lease_expires_at_ms: i64,
    pub lease_generation: i64,
}

/// Failed-attempt release result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkspaceAutonomyBootstrapFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

/// Stable autonomous bootstrap queue failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyBootstrapStoreError {
    #[error("invalid Workspace Autonomy bootstrap claim")]
    InvalidClaim,
    #[error("Workspace Autonomy bootstrap lease was lost")]
    LeaseLost,
    #[error("persisted Workspace Autonomy bootstrap record is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite autonomous bootstrap queue repository.
pub struct WorkspaceAutonomyBootstrapStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyBootstrapStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Build an idempotent autonomous-root bootstrap write for an existing profile.
    ///
    /// The write is a no-op when the Workspace already has either a bootstrap row or a
    /// `goal_root` Task. Callers can therefore place it in the same checked transaction as a
    /// profile transition to autonomous mode.
    #[must_use]
    pub fn ensure_mutation(
        &self,
        profile: &WorkspaceProfileSnapshot,
        actor_id: &str,
        created_at_ms: i64,
    ) -> WorkspaceDomainMutation {
        let ensure = WorkspaceAutonomyBootstrapEnsure {
            tenant_id: profile.tenant_id.as_str(),
            project_id: profile.project_id.as_str(),
            workspace_id: profile.workspace_id.as_str(),
            actor_id,
            objective_title: profile.name.as_str(),
            objective_description: profile.description.as_deref(),
            created_at_ms,
        };
        WorkspaceDomainMutation::new(
            ensure_statement(self.flavor, &ensure),
            DbCountExpectation::at_most(1),
        )
    }

    /// Lease pending or expired bootstrap requests with monotonic fencing.
    pub async fn claim(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<WorkspaceAutonomyBootstrapClaim>, WorkspaceAutonomyBootstrapStoreError> {
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
            .map(|row| bootstrap_claim_from_row(row, worker_id, lease_expires_at_ms))
            .collect()
    }

    /// ACK the exact fenced claim after its Objective and root Task exist.
    pub async fn complete(
        &self,
        claim: &WorkspaceAutonomyBootstrapClaim,
        objective_id: &str,
        root_task_id: &str,
        completed_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyBootstrapStoreError> {
        if [objective_id, root_task_id]
            .iter()
            .any(|value| value.trim().is_empty() || value.chars().count() > 128)
            || completed_at_ms < 0
        {
            return Err(WorkspaceAutonomyBootstrapStoreError::InvalidClaim);
        }
        let result = self
            .db
            .execute(complete_statement(
                self.flavor,
                claim,
                objective_id,
                root_task_id,
                completed_at_ms,
            ))
            .await?;
        require_owned_lease(result)
    }

    /// Release a failed claim for bounded retry or durable dead-lettering.
    pub async fn fail(
        &self,
        claim: &WorkspaceAutonomyBootstrapClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<WorkspaceAutonomyBootstrapFailureOutcome, WorkspaceAutonomyBootstrapStoreError>
    {
        if next_attempt_at_ms < 0
            || last_error.trim().is_empty()
            || last_error.chars().count() > MAX_LAST_ERROR_CHARS
        {
            return Err(WorkspaceAutonomyBootstrapStoreError::InvalidClaim);
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
            return Err(WorkspaceAutonomyBootstrapStoreError::LeaseLost);
        };
        Ok(WorkspaceAutonomyBootstrapFailureOutcome {
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
) -> Result<(), WorkspaceAutonomyBootstrapStoreError> {
    if worker_id.trim().is_empty()
        || worker_id.chars().count() > 191
        || now_ms < 0
        || lease_expires_at_ms <= now_ms
        || !(1..=MAX_BOOTSTRAP_CLAIM_LIMIT).contains(&limit)
    {
        return Err(WorkspaceAutonomyBootstrapStoreError::InvalidClaim);
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
            "UPDATE workspace_autonomy_bootstrap_outbox SET status = 'processing', \
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
                "bootstrap_id IN (SELECT bootstrap_id FROM workspace_autonomy_bootstrap_outbox \
                 WHERE attempt_count < max_attempts AND ((status = 'pending' AND \
                 next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(")) ORDER BY created_at_ms ASC, bootstrap_id ASC LIMIT ")
            .bind(limit)
            .push_static(" FOR UPDATE SKIP LOCKED)"),
        DbSqlFlavor::Sqlite => builder
            .push_static(
                "rowid IN (SELECT rowid FROM workspace_autonomy_bootstrap_outbox WHERE \
                 attempt_count < max_attempts AND ((status = 'pending' AND \
                 next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(")) ORDER BY created_at_ms ASC, bootstrap_id ASC LIMIT ")
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(
            " RETURNING bootstrap_id, tenant_id, project_id, workspace_id, actor_id, \
             objective_title, objective_description, attempt_count, lease_generation",
        )
        .build()
}

fn reap_exhausted_statement(flavor: DbSqlFlavor, now_ms: i64) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_bootstrap_outbox SET status = 'dead_letter', \
             lease_owner = NULL, lease_expires_at_ms = NULL, last_error = \
             COALESCE(last_error, 'autonomy bootstrap lease expired after maximum attempts') \
             WHERE attempt_count >= max_attempts AND ((status = 'pending' AND \
             next_attempt_at_ms <= ",
        )
        .bind(now_ms)
        .push_static(") OR (status = 'processing' AND lease_expires_at_ms <= ")
        .bind(now_ms)
        .push_static("))")
        .build()
}

fn ensure_statement(
    flavor: DbSqlFlavor,
    ensure: &WorkspaceAutonomyBootstrapEnsure<'_>,
) -> DbStatement {
    let bootstrap_id = format!("{RECOVERY_BOOTSTRAP_PREFIX}{}", ensure.workspace_id);
    let builder = DbStatementBuilder::new(flavor)
        .push_static(flavor.insert_or_ignore())
        .push_static(
            " INTO workspace_autonomy_bootstrap_outbox (bootstrap_id, tenant_id, project_id, \
             workspace_id, actor_id, objective_title, objective_description, created_at_ms) \
             SELECT ",
        )
        .bind(bootstrap_id)
        .push_static(", ")
        .bind(ensure.tenant_id)
        .push_static(", ")
        .bind(ensure.project_id)
        .push_static(", ")
        .bind(ensure.workspace_id)
        .push_static(", ")
        .bind(ensure.actor_id)
        .push_static(", ")
        .bind(ensure.objective_title)
        .push_static(", ")
        .bind(ensure.objective_description)
        .push_static(", ")
        .bind(ensure.created_at_ms)
        .push_static(
            " WHERE NOT EXISTS (SELECT 1 FROM workspace_tasks root WHERE root.tenant_id = ",
        )
        .bind(ensure.tenant_id)
        .push_static(" AND root.project_id = ")
        .bind(ensure.project_id)
        .push_static(" AND root.workspace_id = ")
        .bind(ensure.workspace_id)
        .push_static(" AND ");
    let builder = match flavor {
        DbSqlFlavor::Postgres => {
            builder.push_static("root.metadata_json ->> 'task_role' = 'goal_root'")
        }
        DbSqlFlavor::Sqlite => {
            builder.push_static("json_extract(root.metadata_json, '$.task_role') = 'goal_root'")
        }
        DbSqlFlavor::Mysql => builder.push_static(
            "JSON_UNQUOTE(JSON_EXTRACT(root.metadata_json, '$.task_role')) = 'goal_root'",
        ),
    }
    .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres => builder.push_static(" ON CONFLICT (workspace_id) DO NOTHING"),
        DbSqlFlavor::Sqlite | DbSqlFlavor::Mysql => builder,
    }
    .build()
}

fn complete_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceAutonomyBootstrapClaim,
    objective_id: &str,
    root_task_id: &str,
    completed_at_ms: i64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_bootstrap_outbox SET status = 'completed', objective_id = ",
        )
        .bind(objective_id)
        .push_static(", root_task_id = ")
        .bind(root_task_id)
        .push_static(", completed_at_ms = ")
        .bind(completed_at_ms)
        .push_static(
            ", lease_owner = NULL, lease_expires_at_ms = NULL, last_error = NULL WHERE \
             bootstrap_id = ",
        )
        .bind(claim.bootstrap_id.as_str())
        .push_static(" AND tenant_id = ")
        .bind(claim.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(claim.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(claim.workspace_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(claim.worker_id.as_str())
        .push_static(" AND lease_expires_at_ms = ")
        .bind(claim.lease_expires_at_ms)
        .push_static(" AND lease_generation = ")
        .bind(claim.lease_generation)
        .push_static(
            " AND EXISTS (SELECT 1 FROM workspace_objectives objective JOIN workspace_tasks root \
             ON root.tenant_id = objective.tenant_id AND root.project_id = objective.project_id \
             AND root.workspace_id = objective.workspace_id WHERE objective.objective_id = ",
        )
        .bind(objective_id)
        .push_static(" AND objective.tenant_id = ")
        .bind(claim.tenant_id.as_str())
        .push_static(" AND objective.project_id = ")
        .bind(claim.project_id.as_str())
        .push_static(" AND objective.workspace_id = ")
        .bind(claim.workspace_id.as_str())
        .push_static(
            " AND objective.objective_type = 'objective' AND \
             objective.parent_objective_id IS NULL AND root.task_id = ",
        )
        .bind(root_task_id)
        .push_static(" AND ");
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder.push_static(
            "root.metadata_json ->> 'task_role' = 'goal_root' AND \
             root.metadata_json ->> 'objective_id' = objective.objective_id",
        ),
        DbSqlFlavor::Sqlite => builder.push_static(
            "json_extract(root.metadata_json, '$.task_role') = 'goal_root' AND \
             json_extract(root.metadata_json, '$.objective_id') = objective.objective_id",
        ),
        DbSqlFlavor::Mysql => builder.push_static(
            "JSON_UNQUOTE(JSON_EXTRACT(root.metadata_json, '$.task_role')) = 'goal_root' AND \
             JSON_UNQUOTE(JSON_EXTRACT(root.metadata_json, '$.objective_id')) = \
             objective.objective_id",
        ),
    };
    builder.push_static(")").build()
}

fn fail_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceAutonomyBootstrapClaim,
    next_attempt_at_ms: i64,
    last_error: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_bootstrap_outbox SET status = CASE WHEN \
             attempt_count >= max_attempts THEN 'dead_letter' ELSE 'pending' END, \
             next_attempt_at_ms = ",
        )
        .bind(next_attempt_at_ms)
        .push_static(", last_error = ")
        .bind(last_error)
        .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL WHERE bootstrap_id = ")
        .bind(claim.bootstrap_id.as_str())
        .push_static(" AND status = 'processing' AND lease_owner = ")
        .bind(claim.worker_id.as_str())
        .push_static(" AND lease_expires_at_ms = ")
        .bind(claim.lease_expires_at_ms)
        .push_static(" AND lease_generation = ")
        .bind(claim.lease_generation)
        .push_static(" RETURNING status, attempt_count")
        .build()
}

fn bootstrap_claim_from_row(
    row: &DbRow,
    worker_id: &str,
    lease_expires_at_ms: i64,
) -> Result<WorkspaceAutonomyBootstrapClaim, WorkspaceAutonomyBootstrapStoreError> {
    Ok(WorkspaceAutonomyBootstrapClaim {
        bootstrap_id: required_string(row, "bootstrap_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        actor_id: required_string(row, "actor_id")?,
        objective_title: required_string(row, "objective_title")?,
        objective_description: row.get_string("objective_description")?,
        attempt_count: required_i64(row, "attempt_count")?,
        worker_id: worker_id.to_string(),
        lease_expires_at_ms,
        lease_generation: required_i64(row, "lease_generation")?,
    })
}

fn require_owned_lease(
    result: DbExecuteResult,
) -> Result<(), WorkspaceAutonomyBootstrapStoreError> {
    if result.affected_rows == 1 {
        Ok(())
    } else {
        Err(WorkspaceAutonomyBootstrapStoreError::LeaseLost)
    }
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyBootstrapStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAutonomyBootstrapStoreError::InvalidRecord(column))
}

fn required_i64(
    row: &DbRow,
    column: &'static str,
) -> Result<i64, WorkspaceAutonomyBootstrapStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceAutonomyBootstrapStoreError::InvalidRecord(column))
}

#[cfg(test)]
#[path = "autonomy_bootstrap_sql_tests.rs"]
mod sql_tests;
