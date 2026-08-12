//! Fenced durable delivery of runtime-owned Workspace Plan outbox actions.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep,
};
pub use memstack_workspace_service_api::WORKSPACE_PLAN_RUNTIME_EVENT_TYPES;
use serde_json::{Value, json};
use thiserror::Error;

const MAX_CLAIM_LIMIT: i64 = 100;

/// One immutable Plan runtime action held by a fenced lease.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePlanDeliveryClaim {
    pub outbox_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub plan_id: String,
    pub event_type: String,
    pub payload: Value,
    pub metadata: Value,
    pub correlation_id: Option<String>,
    pub plan_node_id: Option<String>,
    pub task_id: Option<String>,
    pub attempt_id: Option<String>,
    pub agent_id: Option<String>,
    pub actor_id: Option<String>,
    pub group_id: String,
    pub attempt_count: u32,
    pub max_attempts: u32,
    pub lease_owner: String,
    pub lease_expires_at: String,
}

/// Durable Provider correlation written before releasing a successful lease.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspacePlanDeliveryCompletion {
    pub correlation_id: String,
    pub conversation_id: String,
    pub provider_id: String,
    pub provider_bot_ref: String,
    pub provider_run_id: String,
    pub accepted_at: String,
}

/// Result of releasing one failed Provider dispatch.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkspacePlanDeliveryFailureOutcome {
    pub attempt_count: u32,
    pub dead_lettered: bool,
}

/// Plan runtime outbox claim, completion, and retry persistence.
pub struct WorkspacePlanDeliveryStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspacePlanDeliveryStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Atomically claim only runtime-owned Plan action events.
    ///
    /// # Errors
    ///
    /// Returns an input, persistence, or record-decoding error.
    pub async fn claim_deliveries(
        &self,
        worker_id: &str,
        now: &str,
        lease_expires_at: &str,
        limit: i64,
    ) -> Result<Vec<WorkspacePlanDeliveryClaim>, WorkspacePlanDeliveryStoreError> {
        validate_claim(worker_id, now, lease_expires_at, limit)?;
        if matches!(self.flavor, DbSqlFlavor::Mysql) {
            return Err(WorkspacePlanDeliveryStoreError::InvalidInput(
                "Plan runtime delivery supports PostgreSQL and SQLite only".to_string(),
            ));
        }
        self.db.execute(reap_exhausted(self.flavor, now)).await?;
        let rows = self
            .db
            .query(claim_statement(
                self.flavor,
                worker_id,
                now,
                lease_expires_at,
                limit,
            ))
            .await?;
        let mut claims = Vec::with_capacity(rows.len());
        for row in rows {
            let mut claim = claim_from_row(&row, worker_id, lease_expires_at)?;
            let context_rows = self
                .db
                .query(context_statement(self.flavor, &claim))
                .await?;
            let context = context_rows
                .first()
                .ok_or(WorkspacePlanDeliveryStoreError::MissingContext)?;
            claim.group_id = required_string(context, "group_id")?;
            claim.task_id = optional_string(context, "workspace_task_id")?;
            claim.attempt_id = optional_string(context, "current_attempt_id")?;
            claim.agent_id = optional_string(context, "assignee_agent_id")?;
            claims.push(claim);
        }
        Ok(claims)
    }

    /// Persist the Provider correlation before handing the row to event publication.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanDeliveryStoreError::LeaseLost`] for a stale or
    /// duplicate completion, and rolls back a conflicting correlation.
    pub async fn complete_delivery(
        &self,
        claim: &WorkspacePlanDeliveryClaim,
        completion: &WorkspacePlanDeliveryCompletion,
    ) -> Result<(), WorkspacePlanDeliveryStoreError> {
        validate_completion(completion)?;
        let result = self
            .db
            .transaction(vec![
                DbTransactionStep::execute_checked(
                    correlation_upsert(self.flavor, claim, completion),
                    DbCountExpectation::exactly(1),
                ),
                DbTransactionStep::execute_checked(
                    complete_statement(self.flavor, claim, completion),
                    DbCountExpectation::exactly(1),
                ),
            ])
            .await;
        match result {
            Ok(_) => Ok(()),
            Err(DbError::TransactionExpectation { step_index: 0, .. }) => {
                Err(WorkspacePlanDeliveryStoreError::CorrelationConflict)
            }
            Err(DbError::TransactionExpectation { step_index: 1, .. }) => {
                Err(WorkspacePlanDeliveryStoreError::LeaseLost)
            }
            Err(error) => Err(error.into()),
        }
    }

    /// Release a failed Provider attempt for retry or durable dead-lettering.
    ///
    /// # Errors
    ///
    /// Returns [`WorkspacePlanDeliveryStoreError::LeaseLost`] when the exact
    /// worker and expiry fence is no longer owned.
    pub async fn fail_delivery(
        &self,
        claim: &WorkspacePlanDeliveryClaim,
        failed_at: &str,
        next_attempt_at: &str,
        last_error: &str,
    ) -> Result<WorkspacePlanDeliveryFailureOutcome, WorkspacePlanDeliveryStoreError> {
        if failed_at.trim().is_empty()
            || next_attempt_at.trim().is_empty()
            || last_error.trim().is_empty()
        {
            return Err(WorkspacePlanDeliveryStoreError::InvalidInput(
                "retry timestamp and stable error code must not be blank".to_string(),
            ));
        }
        let rows = self
            .db
            .query(fail_statement(
                self.flavor,
                claim,
                failed_at,
                next_attempt_at,
                last_error,
            ))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspacePlanDeliveryStoreError::LeaseLost);
        };
        Ok(WorkspacePlanDeliveryFailureOutcome {
            attempt_count: required_u32(row, "attempt_count")?,
            dead_lettered: required_string(row, "status")? == "dead_letter",
        })
    }
}

/// Invalid Plan delivery input, lease, correlation, or persisted record.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspacePlanDeliveryStoreError {
    #[error(transparent)]
    Database(#[from] DbError),
    #[error("Workspace Plan delivery input is invalid: {0}")]
    InvalidInput(String),
    #[error("Workspace Plan delivery record is invalid: {0}")]
    InvalidRecord(String),
    #[error("Workspace Plan delivery JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error("Workspace Plan delivery context is missing")]
    MissingContext,
    #[error("Workspace Plan delivery lease was lost")]
    LeaseLost,
    #[error("Workspace Plan runtime correlation conflicts with persisted state")]
    CorrelationConflict,
}

fn validate_claim(
    worker_id: &str,
    now: &str,
    lease_expires_at: &str,
    limit: i64,
) -> Result<(), WorkspacePlanDeliveryStoreError> {
    if worker_id.trim().is_empty() || now.trim().is_empty() || lease_expires_at.trim().is_empty() {
        return Err(WorkspacePlanDeliveryStoreError::InvalidInput(
            "worker and lease timestamps must not be blank".to_string(),
        ));
    }
    if !(1..=MAX_CLAIM_LIMIT).contains(&limit) {
        return Err(WorkspacePlanDeliveryStoreError::InvalidInput(format!(
            "claim limit must be between 1 and {MAX_CLAIM_LIMIT}"
        )));
    }
    Ok(())
}

fn validate_completion(
    completion: &WorkspacePlanDeliveryCompletion,
) -> Result<(), WorkspacePlanDeliveryStoreError> {
    for (field, value) in [
        ("correlation_id", completion.correlation_id.as_str()),
        ("conversation_id", completion.conversation_id.as_str()),
        ("provider_id", completion.provider_id.as_str()),
        ("provider_bot_ref", completion.provider_bot_ref.as_str()),
        ("provider_run_id", completion.provider_run_id.as_str()),
        ("accepted_at", completion.accepted_at.as_str()),
    ] {
        if value.trim().is_empty() {
            return Err(WorkspacePlanDeliveryStoreError::InvalidInput(format!(
                "{field} must not be blank"
            )));
        }
    }
    Ok(())
}

fn plan_event_filter(mut builder: DbStatementBuilder) -> DbStatementBuilder {
    builder = builder.push_static("event_type IN (");
    for (index, event_type) in WORKSPACE_PLAN_RUNTIME_EVENT_TYPES.iter().enumerate() {
        if index > 0 {
            builder = builder.push_static(", ");
        }
        builder = builder.bind(*event_type);
    }
    builder.push_static(")")
}

fn claim_statement(
    flavor: DbSqlFlavor,
    worker_id: &str,
    now: &str,
    lease_expires_at: &str,
    limit: i64,
) -> DbStatement {
    let candidate_filter = |builder: DbStatementBuilder| {
        plan_event_filter(
            builder
                .push_static("aggregate_type = 'workspace_plan' AND ")
                .push_static("attempt_count < max_attempts AND ((status IN ('pending', 'failed') AND (next_attempt_at IS NULL OR next_attempt_at <= ")
                .bind(now)
                .push_static(") OR (status = 'plan_dispatching' AND lease_expires_at <= ")
                .bind(now)
                .push_static("))) AND "),
        )
    };
    let builder = match flavor {
        DbSqlFlavor::Postgres => candidate_filter(
            DbStatementBuilder::new(flavor)
                .push_static("WITH candidates AS (SELECT outbox_id FROM workspace_outbox WHERE "),
        )
        .push_static(" ORDER BY created_at, outbox_id FOR UPDATE SKIP LOCKED LIMIT ")
        .bind(limit)
        .push_static(") UPDATE workspace_outbox o SET status = 'plan_dispatching', attempt_count = attempt_count + 1, lease_owner = ")
        .bind(worker_id)
        .push_static(", lease_expires_at = ")
        .bind(lease_expires_at)
        .push_static(", next_attempt_at = NULL, last_error = NULL, updated_at = ")
        .bind(now)
        .push_static(" FROM candidates WHERE o.outbox_id = candidates.outbox_id RETURNING o."),
        DbSqlFlavor::Sqlite => candidate_filter(
            DbStatementBuilder::new(flavor)
                .push_static("UPDATE workspace_outbox SET status = 'plan_dispatching', attempt_count = attempt_count + 1, lease_owner = ")
                .bind(worker_id)
                .push_static(", lease_expires_at = ")
                .bind(lease_expires_at)
                .push_static(", next_attempt_at = NULL, last_error = NULL, updated_at = ")
                .bind(now)
                .push_static(" WHERE rowid IN (SELECT rowid FROM workspace_outbox WHERE "),
        )
        .push_static(" ORDER BY created_at, outbox_id LIMIT ")
        .bind(limit)
        .push_static(") RETURNING "),
        DbSqlFlavor::Mysql => DbStatementBuilder::new(flavor)
            .push_static("SELECT outbox_id FROM workspace_outbox WHERE 1 = 0 AND "),
    };
    builder
        .push_static("outbox_id, tenant_id, project_id, workspace_id, aggregate_id, event_type, payload_json, metadata_json, correlation_id, attempt_count, max_attempts")
        .build()
}

fn reap_exhausted(flavor: DbSqlFlavor, now: &str) -> DbStatement {
    plan_event_filter(
        DbStatementBuilder::new(flavor)
            .push_static("UPDATE workspace_outbox SET status = 'dead_letter', lease_owner = NULL, lease_expires_at = NULL, next_attempt_at = NULL, last_error = COALESCE(last_error, 'workspace_plan_delivery_attempts_exhausted'), updated_at = ")
            .bind(now)
            .push_static(" WHERE aggregate_type = 'workspace_plan' AND attempt_count >= max_attempts AND ((status IN ('pending', 'failed') AND (next_attempt_at IS NULL OR next_attempt_at <= ")
            .bind(now)
            .push_static(") OR (status = 'plan_dispatching' AND lease_expires_at <= ")
            .bind(now)
            .push_static("))) AND "),
    )
    .build()
}

fn context_statement(flavor: DbSqlFlavor, claim: &WorkspacePlanDeliveryClaim) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT profile.group_id, node.workspace_task_id, node.current_attempt_id, node.assignee_agent_id FROM workspace_profiles profile LEFT JOIN workspace_plan_nodes node ON node.tenant_id = profile.tenant_id AND node.project_id = profile.project_id AND node.workspace_id = profile.workspace_id AND node.plan_id = ")
        .bind(claim.plan_id.as_str())
        .push_static(" AND node.node_id = ")
        .bind(claim.plan_node_id.as_deref())
        .push_static(" WHERE profile.tenant_id = ")
        .bind(claim.tenant_id.as_str())
        .push_static(" AND profile.project_id = ")
        .bind(claim.project_id.as_str())
        .push_static(" AND profile.workspace_id = ")
        .bind(claim.workspace_id.as_str())
        .push_static(" LIMIT 1")
        .build()
}

fn correlation_upsert(
    flavor: DbSqlFlavor,
    claim: &WorkspacePlanDeliveryClaim,
    completion: &WorkspacePlanDeliveryCompletion,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_agent_runtime_correlations (correlation_id, tenant_id, project_id, workspace_id, user_id, task_id, attempt_id, plan_id, plan_node_id, conversation_id, bcs_group_id, delivery_request_id, provider_run_id, provider_id, provider_bot_ref, status, created_at, updated_at) VALUES (")
        .bind(completion.correlation_id.as_str())
        .push_static(", ")
        .bind(claim.tenant_id.as_str())
        .push_static(", ")
        .bind(claim.project_id.as_str())
        .push_static(", ")
        .bind(claim.workspace_id.as_str())
        .push_static(", ")
        .bind(claim.actor_id.as_deref())
        .push_static(", ")
        .bind(claim.task_id.as_deref())
        .push_static(", ")
        .bind(claim.attempt_id.as_deref())
        .push_static(", ")
        .bind(claim.plan_id.as_str())
        .push_static(", ")
        .bind(claim.plan_node_id.as_deref())
        .push_static(", ")
        .bind(completion.conversation_id.as_str())
        .push_static(", ")
        .bind(claim.group_id.as_str())
        .push_static(", ")
        .bind(claim.outbox_id.as_str())
        .push_static(", ")
        .bind(completion.provider_run_id.as_str())
        .push_static(", ")
        .bind(completion.provider_id.as_str())
        .push_static(", ")
        .bind(completion.provider_bot_ref.as_str())
        .push_static(", 'running', ")
        .bind(completion.accepted_at.as_str())
        .push_static(", ")
        .bind(completion.accepted_at.as_str())
        .push_static(") ON CONFLICT(correlation_id) DO UPDATE SET updated_at = excluded.updated_at WHERE workspace_agent_runtime_correlations.tenant_id = excluded.tenant_id AND workspace_agent_runtime_correlations.project_id = excluded.project_id AND workspace_agent_runtime_correlations.workspace_id = excluded.workspace_id AND workspace_agent_runtime_correlations.plan_id = excluded.plan_id AND COALESCE(workspace_agent_runtime_correlations.plan_node_id, '') = COALESCE(excluded.plan_node_id, '') AND workspace_agent_runtime_correlations.conversation_id = excluded.conversation_id AND workspace_agent_runtime_correlations.delivery_request_id = excluded.delivery_request_id AND workspace_agent_runtime_correlations.provider_run_id = excluded.provider_run_id")
        .build()
}

fn complete_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspacePlanDeliveryClaim,
    completion: &WorkspacePlanDeliveryCompletion,
) -> DbStatement {
    let patch = json!({
        "plan_runtime_dispatch": {
            "status": "accepted",
            "correlation_id": &completion.correlation_id,
            "conversation_id": &completion.conversation_id,
            "provider_id": &completion.provider_id,
            "provider_bot_ref": &completion.provider_bot_ref,
            "provider_run_id": &completion.provider_run_id,
            "accepted_at": &completion.accepted_at,
        }
    })
    .to_string();
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_outbox SET status = 'runtime_dispatched', lease_owner = NULL, lease_expires_at = NULL, last_error = NULL, next_attempt_at = NULL, correlation_id = ")
        .bind(completion.correlation_id.as_str())
        .push_static(", metadata_json = ");
    builder = match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static("metadata_json || ")
            .bind(patch)
            .push_static("::jsonb"),
        DbSqlFlavor::Sqlite => builder
            .push_static("json_patch(metadata_json, ")
            .bind(patch)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder
            .push_static("JSON_MERGE_PATCH(metadata_json, ")
            .bind(patch)
            .push_static(")"),
    };
    fenced_update(builder, claim)
        .push_static(" AND lease_expires_at = ")
        .bind(claim.lease_expires_at.as_str())
        .build()
}

fn fail_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspacePlanDeliveryClaim,
    failed_at: &str,
    next_attempt_at: &str,
    last_error: &str,
) -> DbStatement {
    fenced_update(
        DbStatementBuilder::new(flavor)
            .push_static("UPDATE workspace_outbox SET status = CASE WHEN attempt_count >= max_attempts THEN 'dead_letter' ELSE 'failed' END, lease_owner = NULL, lease_expires_at = NULL, last_error = ")
            .bind(last_error)
            .push_static(", next_attempt_at = CASE WHEN attempt_count >= max_attempts THEN NULL ELSE ")
            .bind(next_attempt_at)
            .push_static(" END, updated_at = ")
            .bind(failed_at),
        claim,
    )
    .push_static(" AND lease_expires_at = ")
    .bind(claim.lease_expires_at.as_str())
    .push_static(" RETURNING status, attempt_count")
    .build()
}

fn fenced_update(
    builder: DbStatementBuilder,
    claim: &WorkspacePlanDeliveryClaim,
) -> DbStatementBuilder {
    builder
        .push_static(" WHERE outbox_id = ")
        .bind(claim.outbox_id.as_str())
        .push_static(" AND status = 'plan_dispatching' AND lease_owner = ")
        .bind(claim.lease_owner.as_str())
}

fn claim_from_row(
    row: &DbRow,
    worker_id: &str,
    lease_expires_at: &str,
) -> Result<WorkspacePlanDeliveryClaim, WorkspacePlanDeliveryStoreError> {
    let payload = required_json(row, "payload_json")?;
    let plan_node_id = optional_payload_string(&payload, "node_id")?;
    let actor_id = optional_payload_string(&payload, "actor_id")?;
    Ok(WorkspacePlanDeliveryClaim {
        outbox_id: required_string(row, "outbox_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        plan_id: required_string(row, "aggregate_id")?,
        event_type: required_string(row, "event_type")?,
        payload,
        metadata: required_json(row, "metadata_json")?,
        correlation_id: optional_string(row, "correlation_id")?,
        plan_node_id,
        task_id: None,
        attempt_id: None,
        agent_id: None,
        actor_id,
        group_id: String::new(),
        attempt_count: required_u32(row, "attempt_count")?,
        max_attempts: required_u32(row, "max_attempts")?,
        lease_owner: worker_id.to_string(),
        lease_expires_at: lease_expires_at.to_string(),
    })
}

fn optional_payload_string(
    payload: &Value,
    field: &'static str,
) -> Result<Option<String>, WorkspacePlanDeliveryStoreError> {
    match payload.get(field) {
        None | Some(Value::Null) => Ok(None),
        Some(Value::String(value)) if !value.trim().is_empty() => Ok(Some(value.clone())),
        Some(Value::String(_)) | Some(_) => Err(WorkspacePlanDeliveryStoreError::InvalidRecord(
            format!("payload {field} must be a non-blank string or null"),
        )),
    }
}

fn required_json(
    row: &DbRow,
    field: &'static str,
) -> Result<Value, WorkspacePlanDeliveryStoreError> {
    serde_json::from_str(&required_string(row, field)?)
        .map_err(WorkspacePlanDeliveryStoreError::InvalidJson)
}

fn required_string(
    row: &DbRow,
    field: &'static str,
) -> Result<String, WorkspacePlanDeliveryStoreError> {
    row.get_string(field)?.ok_or_else(|| {
        WorkspacePlanDeliveryStoreError::InvalidRecord(format!("{field} is missing"))
    })
}

fn optional_string(
    row: &DbRow,
    field: &'static str,
) -> Result<Option<String>, WorkspacePlanDeliveryStoreError> {
    Ok(row.get_string(field)?)
}

fn required_u32(row: &DbRow, field: &'static str) -> Result<u32, WorkspacePlanDeliveryStoreError> {
    let value = row.get_i64(field)?.ok_or_else(|| {
        WorkspacePlanDeliveryStoreError::InvalidRecord(format!("{field} is missing"))
    })?;
    u32::try_from(value).map_err(|_| {
        WorkspacePlanDeliveryStoreError::InvalidRecord(format!("{field} is outside u32"))
    })
}

#[cfg(test)]
#[path = "plan_delivery_sql_tests.rs"]
mod tests;
