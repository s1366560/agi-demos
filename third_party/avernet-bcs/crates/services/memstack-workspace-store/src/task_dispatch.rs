//! Durable, fenced delivery queue for Workspace execution Tasks.

use bcs_db_api::{DbExecuteResult, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder};

use crate::{WorkspaceTaskScope, WorkspaceTaskStoreError};

const MAX_DISPATCH_CLAIM_LIMIT: i64 = 100;

/// Immutable dispatch snapshot inserted in the originating Task transaction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskDispatchWrite {
    pub dispatch_id: String,
    pub scope: WorkspaceTaskScope,
    pub task_id: String,
    pub attempt_id: Option<String>,
    pub plan_id: Option<String>,
    pub plan_node_id: Option<String>,
    pub user_id: String,
    pub agent_id: String,
    pub workspace_agent_binding_id: String,
    pub conversation_id: String,
    pub delivery_request_id: String,
    pub created_at_ms: i64,
}

/// One currently owned Task dispatch lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskDispatchClaim {
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
    pub bot_uuid: String,
    pub group_id: String,
    pub conversation_id: String,
    pub delivery_request_id: String,
    pub task_title: String,
    pub task_description: Option<String>,
    pub task_status: String,
    pub attempt_count: i64,
    pub worker_id: String,
    pub lease_expires_at_ms: i64,
    pub lease_generation: i64,
}

/// Failed-attempt release result.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkspaceTaskDispatchFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

impl WorkspaceTaskDispatchWrite {
    /// Build the insert-select that snapshots the active binding, BCS group, and Task content.
    #[must_use]
    pub(crate) fn insert_statement(&self, flavor: DbSqlFlavor) -> DbStatement {
        DbStatementBuilder::new(flavor)
            .push_static(
                "INSERT INTO workspace_task_dispatch_outbox (dispatch_id, tenant_id, project_id, \
                 workspace_id, task_id, attempt_id, plan_id, plan_node_id, user_id, agent_id, \
                 workspace_agent_binding_id, bot_uuid, \
                 group_id, conversation_id, delivery_request_id, task_title, task_description, \
                 status, attempt_count, max_attempts, next_attempt_at_ms, lease_generation, \
                 created_at_ms) SELECT ",
            )
            .bind(self.dispatch_id.as_str())
            .push_static(", task.tenant_id, task.project_id, task.workspace_id, task.task_id, ")
            .bind(self.attempt_id.clone())
            .push_static(", ")
            .bind(self.plan_id.clone())
            .push_static(", ")
            .bind(self.plan_node_id.clone())
            .push_static(", task.created_by, binding.agent_id, binding.binding_id, binding.bot_uuid, profile.group_id, ")
            .bind(self.conversation_id.as_str())
            .push_static(", ")
            .bind(self.delivery_request_id.as_str())
            .push_static(", task.title, task.description, 'pending', 0, 8, 0, 0, ")
            .bind(self.created_at_ms)
            .push_static(" FROM workspace_tasks task JOIN workspace_profiles profile ON \
                          profile.tenant_id = task.tenant_id AND profile.project_id = task.project_id \
                          AND profile.workspace_id = task.workspace_id JOIN workspace_agent_bindings \
                          binding ON binding.tenant_id = task.tenant_id AND binding.project_id = \
                          task.project_id AND binding.workspace_id = task.workspace_id AND \
                          binding.binding_id = ")
            .bind(self.workspace_agent_binding_id.as_str())
            .push_static(" AND binding.agent_id = ")
            .bind(self.agent_id.as_str())
            .push_static(" AND binding.is_active = TRUE WHERE task.tenant_id = ")
            .bind(self.scope.tenant_id.as_str())
            .push_static(" AND task.project_id = ")
            .bind(self.scope.project_id.as_str())
            .push_static(" AND task.workspace_id = ")
            .bind(self.scope.workspace_id.as_str())
            .push_static(" AND task.task_id = ")
            .bind(self.task_id.as_str())
            .push_static(" AND task.created_by = ")
            .bind(self.user_id.as_str())
            .build()
    }
}

impl crate::WorkspaceTaskStore<'_> {
    /// Lease pending or expired Task dispatches with a monotonic fencing generation.
    pub async fn claim_task_dispatches(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<WorkspaceTaskDispatchClaim>, WorkspaceTaskStoreError> {
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
            .map(|row| dispatch_claim_from_row(row, worker_id, lease_expires_at_ms))
            .collect()
    }

    /// Persist or verify the runtime correlation before any Provider side effect.
    pub async fn prepare_task_dispatch_correlation(
        &self,
        claim: &WorkspaceTaskDispatchClaim,
    ) -> Result<(), WorkspaceTaskStoreError> {
        self.db
            .execute(correlation_insert(self.flavor, claim))
            .await?;
        let rows = self
            .db
            .query(correlation_select(self.flavor, claim))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceTaskStoreError::InvalidRecord(
                "runtime correlation",
            ));
        };
        for (column, expected) in [
            ("tenant_id", claim.tenant_id.as_str()),
            ("project_id", claim.project_id.as_str()),
            ("workspace_id", claim.workspace_id.as_str()),
            ("user_id", claim.user_id.as_str()),
            ("task_id", claim.task_id.as_str()),
            ("conversation_id", claim.conversation_id.as_str()),
            ("delivery_request_id", claim.delivery_request_id.as_str()),
            ("provider_run_id", claim.delivery_request_id.as_str()),
            ("bcs_group_id", claim.group_id.as_str()),
            ("provider_id", "memstack-workspace-agent-runtime"),
            ("provider_bot_ref", claim.agent_id.as_str()),
        ] {
            if required_string(row, column)? != expected {
                return Err(WorkspaceTaskStoreError::DispatchCorrelationConflict);
            }
        }
        for (column, expected) in [
            ("attempt_id", claim.attempt_id.as_deref()),
            ("plan_id", claim.plan_id.as_deref()),
            ("plan_node_id", claim.plan_node_id.as_deref()),
        ] {
            if row.get_string(column)?.as_deref() != expected {
                return Err(WorkspaceTaskStoreError::DispatchCorrelationConflict);
            }
        }
        Ok(())
    }

    /// ACK a currently owned lease. A stale generation cannot complete a re-leased row.
    pub async fn complete_task_dispatch(
        &self,
        claim: &WorkspaceTaskDispatchClaim,
        delivered_at_ms: i64,
    ) -> Result<(), WorkspaceTaskStoreError> {
        if delivered_at_ms < 0 {
            return Err(WorkspaceTaskStoreError::InvalidDispatchClaim);
        }
        let result = self
            .db
            .execute(complete_statement(self.flavor, claim, delivered_at_ms))
            .await?;
        require_owned_lease(result)
    }

    /// Release a failed lease for retry or durable dead-lettering.
    pub async fn fail_task_dispatch(
        &self,
        claim: &WorkspaceTaskDispatchClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<WorkspaceTaskDispatchFailureOutcome, WorkspaceTaskStoreError> {
        if next_attempt_at_ms < 0 || last_error.trim().is_empty() {
            return Err(WorkspaceTaskStoreError::InvalidDispatchClaim);
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
            return Err(WorkspaceTaskStoreError::DispatchLeaseLost);
        };
        Ok(WorkspaceTaskDispatchFailureOutcome {
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
) -> Result<(), WorkspaceTaskStoreError> {
    if worker_id.trim().is_empty()
        || now_ms < 0
        || lease_expires_at_ms <= now_ms
        || !(1..=MAX_DISPATCH_CLAIM_LIMIT).contains(&limit)
    {
        return Err(WorkspaceTaskStoreError::InvalidDispatchClaim);
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
            "UPDATE workspace_task_dispatch_outbox SET status = 'delivering', \
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
                "dispatch_id IN (SELECT dispatch_id FROM workspace_task_dispatch_outbox \
                          WHERE attempt_count < max_attempts AND ((status = 'pending' AND \
                          next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(
                ") ) ORDER BY created_at_ms ASC, dispatch_id ASC FOR UPDATE SKIP LOCKED LIMIT ",
            )
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Sqlite => builder
            .push_static(
                "rowid IN (SELECT rowid FROM workspace_task_dispatch_outbox WHERE \
                          attempt_count < max_attempts AND ((status = 'pending' AND \
                          next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(") ) ORDER BY created_at_ms ASC, dispatch_id ASC LIMIT ")
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(
            " RETURNING dispatch_id, tenant_id, project_id, workspace_id, task_id, \
                      attempt_id, plan_id, plan_node_id, user_id, agent_id, bot_uuid, group_id, \
                      conversation_id, delivery_request_id, task_title, task_description, \
                      attempt_count, lease_generation, (SELECT status FROM workspace_tasks task \
                      WHERE task.task_id = workspace_task_dispatch_outbox.task_id) AS task_status",
        )
        .build()
}

fn reap_exhausted_statement(flavor: DbSqlFlavor, now_ms: i64) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_task_dispatch_outbox SET status = 'dead_letter', \
                      lease_owner = NULL, lease_expires_at_ms = NULL, last_error = \
                      COALESCE(last_error, 'task dispatch lease expired after maximum attempts') \
                      WHERE attempt_count >= max_attempts AND ((status = 'pending' AND \
                      next_attempt_at_ms <= ",
        )
        .bind(now_ms)
        .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
        .bind(now_ms)
        .push_static("))")
        .build()
}

fn complete_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceTaskDispatchClaim,
    delivered_at_ms: i64,
) -> DbStatement {
    fenced_update(
        flavor,
        claim,
        "UPDATE workspace_task_dispatch_outbox SET status = 'delivered', delivered_at_ms = ",
    )
    .bind(delivered_at_ms)
    .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL, last_error = NULL WHERE ")
    .push_static("dispatch_id = ")
    .bind(claim.dispatch_id.as_str())
    .push_static(" AND status = 'delivering' AND lease_owner = ")
    .bind(claim.worker_id.as_str())
    .push_static(" AND lease_expires_at_ms = ")
    .bind(claim.lease_expires_at_ms)
    .push_static(" AND lease_generation = ")
    .bind(claim.lease_generation)
    .build()
}

fn fail_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceTaskDispatchClaim,
    next_attempt_at_ms: i64,
    last_error: &str,
) -> DbStatement {
    fenced_update(flavor, claim, "UPDATE workspace_task_dispatch_outbox SET status = CASE WHEN attempt_count >= max_attempts THEN 'dead_letter' ELSE 'pending' END, next_attempt_at_ms = ")
        .bind(next_attempt_at_ms)
        .push_static(", last_error = ").bind(last_error)
        .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL WHERE dispatch_id = ")
        .bind(claim.dispatch_id.as_str())
        .push_static(" AND status = 'delivering' AND lease_owner = ").bind(claim.worker_id.as_str())
        .push_static(" AND lease_expires_at_ms = ").bind(claim.lease_expires_at_ms)
        .push_static(" AND lease_generation = ").bind(claim.lease_generation)
        .push_static(" RETURNING status, attempt_count").build()
}

fn fenced_update(
    flavor: DbSqlFlavor,
    _claim: &WorkspaceTaskDispatchClaim,
    prefix: &'static str,
) -> DbStatementBuilder {
    DbStatementBuilder::new(flavor).push_static(prefix)
}

fn correlation_insert(flavor: DbSqlFlavor, claim: &WorkspaceTaskDispatchClaim) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_agent_runtime_correlations (correlation_id, tenant_id, \
                      project_id, workspace_id, task_id, attempt_id, plan_id, plan_node_id, \
                      conversation_id, delivery_request_id, provider_run_id, user_id, bcs_group_id, \
                      provider_id, provider_bot_ref, status, created_at, updated_at) VALUES (")
        .bind(claim.delivery_request_id.as_str())
        .push_static(", ").bind(claim.tenant_id.as_str())
        .push_static(", ").bind(claim.project_id.as_str())
        .push_static(", ").bind(claim.workspace_id.as_str())
        .push_static(", ").bind(claim.task_id.as_str())
        .push_static(", ").bind(claim.attempt_id.clone())
        .push_static(", ").bind(claim.plan_id.clone())
        .push_static(", ").bind(claim.plan_node_id.clone())
        .push_static(", ").bind(claim.conversation_id.as_str())
        .push_static(", ").bind(claim.delivery_request_id.as_str())
        .push_static(", ").bind(claim.delivery_request_id.as_str())
        .push_static(", ").bind(claim.user_id.as_str())
        .push_static(", ").bind(claim.group_id.as_str())
        .push_static(", 'memstack-workspace-agent-runtime', ").bind(claim.agent_id.as_str())
        .push_static(", 'pending', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(correlation_id) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn correlation_select(flavor: DbSqlFlavor, claim: &WorkspaceTaskDispatchClaim) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT tenant_id, project_id, workspace_id, user_id, task_id, attempt_id, plan_id, \
                      plan_node_id, conversation_id, delivery_request_id, provider_run_id, \
                      bcs_group_id, provider_id, provider_bot_ref FROM \
                      workspace_agent_runtime_correlations WHERE \
                      correlation_id = ",
        )
        .bind(claim.delivery_request_id.as_str())
        .push_static(" AND tenant_id = ")
        .bind(claim.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(claim.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(claim.workspace_id.as_str())
        .build()
}

fn dispatch_claim_from_row(
    row: &DbRow,
    worker_id: &str,
    lease_expires_at_ms: i64,
) -> Result<WorkspaceTaskDispatchClaim, WorkspaceTaskStoreError> {
    Ok(WorkspaceTaskDispatchClaim {
        dispatch_id: required_string(row, "dispatch_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        task_id: required_string(row, "task_id")?,
        attempt_id: row.get_string("attempt_id")?,
        plan_id: row.get_string("plan_id")?,
        plan_node_id: row.get_string("plan_node_id")?,
        user_id: required_string(row, "user_id")?,
        agent_id: required_string(row, "agent_id")?,
        bot_uuid: required_string(row, "bot_uuid")?,
        group_id: required_string(row, "group_id")?,
        conversation_id: required_string(row, "conversation_id")?,
        delivery_request_id: required_string(row, "delivery_request_id")?,
        task_title: required_string(row, "task_title")?,
        task_description: row.get_string("task_description")?,
        task_status: required_string(row, "task_status")?,
        attempt_count: required_i64(row, "attempt_count")?,
        worker_id: worker_id.to_string(),
        lease_expires_at_ms,
        lease_generation: required_i64(row, "lease_generation")?,
    })
}

fn require_owned_lease(result: DbExecuteResult) -> Result<(), WorkspaceTaskStoreError> {
    if result.affected_rows == 1 {
        Ok(())
    } else {
        Err(WorkspaceTaskStoreError::DispatchLeaseLost)
    }
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspaceTaskStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(column))
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceTaskStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(column))
}

#[cfg(test)]
#[path = "task_dispatch_sql_tests.rs"]
mod sql_tests;
