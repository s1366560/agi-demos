//! Durable delivery snapshots and recovery claims for Workspace messages.

use bcs_db_api::{DbExecuteResult, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder};

use crate::message::{
    WorkspaceMessageDeliveryTarget, WorkspaceMessageRecord, WorkspaceMessageStore,
    WorkspaceMessageStoreError, WorkspaceMessageWrite, message_from_row,
};

const MAX_DELIVERY_CLAIM_LIMIT: i64 = 100;

/// One leased delivery containing the immutable target and durable message.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceMessageDeliveryClaim {
    pub tenant_id: String,
    pub project_id: String,
    pub group_id: String,
    pub session_id: String,
    pub correlation_id: String,
    pub message: WorkspaceMessageRecord,
    pub target: WorkspaceMessageDeliveryTarget,
    pub attempt_count: i64,
    pub worker_id: String,
    pub lease_expires_at_ms: i64,
}

/// Result of releasing one failed delivery attempt.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct WorkspaceMessageDeliveryFailureOutcome {
    pub attempt_count: i64,
    pub dead_lettered: bool,
}

impl WorkspaceMessageStore<'_> {
    /// Atomically lease pending or expired message deliveries for one worker.
    ///
    /// # Errors
    ///
    /// Returns an input, database, or persisted-record error.
    pub async fn claim_deliveries(
        &self,
        worker_id: &str,
        now_ms: i64,
        lease_expires_at_ms: i64,
        limit: i64,
    ) -> Result<Vec<WorkspaceMessageDeliveryClaim>, WorkspaceMessageStoreError> {
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
        let mut claims = Vec::with_capacity(rows.len());
        for row in rows {
            let tenant_id = required_string(&row, "tenant_id")?;
            let project_id = required_string(&row, "project_id")?;
            let workspace_id = required_string(&row, "workspace_id")?;
            let message_id = required_string(&row, "bcs_message_id")?;
            let group_id = required_string(&row, "group_id")?;
            let message_rows = self
                .db
                .query(delivery_message_envelope_select(
                    self.flavor,
                    &tenant_id,
                    &project_id,
                    &workspace_id,
                    &message_id,
                    &group_id,
                ))
                .await?;
            let message_row = message_rows.first().ok_or_else(|| {
                WorkspaceMessageStoreError::InvalidRecord(format!(
                    "claimed delivery message {message_id} is missing"
                ))
            })?;
            claims.push(WorkspaceMessageDeliveryClaim {
                tenant_id,
                project_id,
                group_id,
                session_id: required_string(message_row, "session_id")?,
                correlation_id: required_string(message_row, "correlation_id")?,
                message: message_from_row(message_row)?,
                target: delivery_target_from_row(&row)?,
                attempt_count: required_i64(&row, "attempt_count")?,
                worker_id: worker_id.to_string(),
                lease_expires_at_ms,
            });
        }
        Ok(claims)
    }

    /// Complete one currently owned delivery lease.
    ///
    /// # Errors
    ///
    /// Returns `DeliveryLeaseLost` for a stale claim or preserves a database failure.
    pub async fn complete_delivery(
        &self,
        claim: &WorkspaceMessageDeliveryClaim,
        delivered_at_ms: i64,
    ) -> Result<(), WorkspaceMessageStoreError> {
        if delivered_at_ms < 0 {
            return Err(WorkspaceMessageStoreError::InvalidDeliveryClaim(
                "delivered_at_ms must be non-negative".to_string(),
            ));
        }
        let result = self
            .db
            .execute(complete_statement(self.flavor, claim, delivered_at_ms))
            .await?;
        require_owned_lease(result)
    }

    /// Release one failed delivery for retry or move it to the dead-letter state.
    ///
    /// # Errors
    ///
    /// Returns `DeliveryLeaseLost` for a stale claim or preserves a database failure.
    pub async fn fail_delivery(
        &self,
        claim: &WorkspaceMessageDeliveryClaim,
        next_attempt_at_ms: i64,
        last_error: &str,
    ) -> Result<WorkspaceMessageDeliveryFailureOutcome, WorkspaceMessageStoreError> {
        if next_attempt_at_ms < 0 {
            return Err(WorkspaceMessageStoreError::InvalidDeliveryClaim(
                "next_attempt_at_ms must be non-negative".to_string(),
            ));
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
            return Err(WorkspaceMessageStoreError::DeliveryLeaseLost);
        };
        let status = required_string(row, "status")?;
        Ok(WorkspaceMessageDeliveryFailureOutcome {
            attempt_count: required_i64(row, "attempt_count")?,
            dead_lettered: status == "dead_letter",
        })
    }
}

pub(crate) fn delivery_snapshot_insert(
    flavor: DbSqlFlavor,
    write: &WorkspaceMessageWrite,
    mentions: &[String],
) -> Result<Option<DbStatement>, WorkspaceMessageStoreError> {
    if mentions.is_empty() {
        return Ok(None);
    }
    let mut builder = DbStatementBuilder::new(flavor).push_static(
        "INSERT INTO workspace_message_delivery_outbox (tenant_id, project_id, workspace_id, \
         bcs_message_id, group_id, target_order, agent_id, bot_uuid, display_name, status, \
         attempt_count, next_attempt_at_ms, created_at_ms) ",
    );
    for (index, mention) in mentions.iter().enumerate() {
        if index > 0 {
            builder = builder.push_static(" UNION ALL ");
        }
        let target_order = i64::try_from(index).map_err(|_| {
            WorkspaceMessageStoreError::InvalidRecord(
                "delivery target order exceeds i64".to_string(),
            )
        })?;
        builder = builder
            .push_static("SELECT ")
            .bind(write.scope.tenant_id.as_str())
            .push_static(", ")
            .bind(write.scope.project_id.as_str())
            .push_static(", ")
            .bind(write.scope.workspace_id.as_str())
            .push_static(", ")
            .bind(write.message_id.as_str())
            .push_static(", message.group_id, ")
            .bind(target_order)
            .push_static(
                ", binding.agent_id, binding.bot_uuid, binding.display_name, \
                           'pending', 0, 0, ",
            )
            .bind(write.created_at_ms)
            .push_static(
                " FROM workspace_agent_bindings binding JOIN bcs_messages message \
                           ON message.message_id = ",
            )
            .bind(write.message_id.as_str())
            .push_static(" WHERE binding.tenant_id = ")
            .bind(write.scope.tenant_id.as_str())
            .push_static(" AND binding.project_id = ")
            .bind(write.scope.project_id.as_str())
            .push_static(" AND binding.workspace_id = ")
            .bind(write.scope.workspace_id.as_str())
            .push_static(" AND binding.agent_id = ")
            .bind(mention.as_str())
            .push_static(" AND binding.is_active = TRUE");
    }
    Ok(Some(builder.build()))
}

pub(crate) fn delivery_targets_select(
    flavor: DbSqlFlavor,
    workspace_id: &str,
    message_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT agent_id, bot_uuid, display_name FROM workspace_message_delivery_outbox \
             WHERE workspace_id = ",
        )
        .bind(workspace_id)
        .push_static(" AND bcs_message_id = ")
        .bind(message_id)
        .push_static(" ORDER BY target_order ASC")
        .build()
}

pub(crate) fn delivery_targets_from_rows(
    rows: &[DbRow],
) -> Result<Vec<WorkspaceMessageDeliveryTarget>, WorkspaceMessageStoreError> {
    rows.iter().map(delivery_target_from_row).collect()
}

fn validate_claim(
    worker_id: &str,
    now_ms: i64,
    lease_expires_at_ms: i64,
    limit: i64,
) -> Result<(), WorkspaceMessageStoreError> {
    if worker_id.trim().is_empty() {
        return Err(WorkspaceMessageStoreError::InvalidDeliveryClaim(
            "worker_id must not be blank".to_string(),
        ));
    }
    if now_ms < 0 || lease_expires_at_ms <= now_ms {
        return Err(WorkspaceMessageStoreError::InvalidDeliveryClaim(
            "delivery lease must end after a non-negative now_ms".to_string(),
        ));
    }
    if !(1..=MAX_DELIVERY_CLAIM_LIMIT).contains(&limit) {
        return Err(WorkspaceMessageStoreError::InvalidDeliveryClaim(format!(
            "delivery claim limit must be between 1 and {MAX_DELIVERY_CLAIM_LIMIT}"
        )));
    }
    Ok(())
}

pub(crate) fn claim_statement(
    flavor: DbSqlFlavor,
    worker_id: &str,
    now_ms: i64,
    lease_expires_at_ms: i64,
    limit: i64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_message_delivery_outbox SET status = 'delivering', \
                      attempt_count = attempt_count + 1, lease_owner = ",
        )
        .bind(worker_id)
        .push_static(", lease_expires_at_ms = ")
        .bind(lease_expires_at_ms)
        .push_static(" WHERE ");
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder
            .push_static(
                "(workspace_id, bcs_message_id, agent_id) IN (SELECT workspace_id, \
                          bcs_message_id, agent_id FROM workspace_message_delivery_outbox WHERE ",
            )
            .push_static(
                "attempt_count < max_attempts AND ((status = 'pending' AND \
                          next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(
                ")) ORDER BY created_at_ms ASC, workspace_id ASC, bcs_message_id ASC, \
                          target_order ASC FOR UPDATE SKIP LOCKED LIMIT ",
            )
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Sqlite => builder
            .push_static("rowid IN (SELECT rowid FROM workspace_message_delivery_outbox WHERE ")
            .push_static(
                "attempt_count < max_attempts AND ((status = 'pending' AND \
                          next_attempt_at_ms <= ",
            )
            .bind(now_ms)
            .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
            .bind(now_ms)
            .push_static(
                ")) ORDER BY created_at_ms ASC, workspace_id ASC, bcs_message_id ASC, \
                          target_order ASC LIMIT ",
            )
            .bind(limit)
            .push_static(")"),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(
            " RETURNING tenant_id, project_id, workspace_id, bcs_message_id, group_id, agent_id, \
             bot_uuid, display_name, attempt_count",
        )
        .build()
}

fn delivery_message_envelope_select(
    flavor: DbSqlFlavor,
    tenant_id: &str,
    project_id: &str,
    workspace_id: &str,
    message_id: &str,
    group_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT message.message_id, message.group_id, message.workspace_id, \
             message.sender_id, message.sender_type, message.content, message.mentions_json, \
             message.parent_message_id, message.metadata_json, message.created_at, \
             message.session_id, correlation.correlation_id FROM bcs_messages message JOIN \
             workspace_message_correlations correlation ON correlation.tenant_id = ",
        )
        .bind(tenant_id)
        .push_static(" AND correlation.project_id = ")
        .bind(project_id)
        .push_static(" AND correlation.workspace_id = ")
        .bind(workspace_id)
        .push_static(
            " AND correlation.bcs_message_id = message.message_id AND \
                      correlation.bcs_session_id = message.session_id WHERE message.env = \
                      'memstack' AND message.message_id = ",
        )
        .bind(message_id)
        .push_static(" AND message.workspace_id = ")
        .bind(workspace_id)
        .push_static(" AND message.group_id = ")
        .bind(group_id)
        .push_static(" LIMIT 1")
        .build()
}

pub(crate) fn reap_exhausted_statement(flavor: DbSqlFlavor, now_ms: i64) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_message_delivery_outbox SET status = 'dead_letter', \
             lease_owner = NULL, lease_expires_at_ms = NULL, last_error = \
             COALESCE(last_error, 'delivery lease expired after maximum attempts') WHERE \
             attempt_count >= max_attempts AND ((status = 'pending' AND next_attempt_at_ms <= ",
        )
        .bind(now_ms)
        .push_static(") OR (status = 'delivering' AND lease_expires_at_ms <= ")
        .bind(now_ms)
        .push_static("))")
        .build()
}

fn complete_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceMessageDeliveryClaim,
    delivered_at_ms: i64,
) -> DbStatement {
    update_builder(
        flavor,
        "UPDATE workspace_message_delivery_outbox SET status = ",
    )
    .bind("delivered")
    .push_static(", delivered_at_ms = ")
    .bind(delivered_at_ms)
    .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL, last_error = NULL WHERE ")
    .push_static("workspace_id = ")
    .bind(claim.message.workspace_id.as_str())
    .push_static(" AND bcs_message_id = ")
    .bind(claim.message.id.as_str())
    .push_static(" AND agent_id = ")
    .bind(claim.target.agent_id.as_str())
    .push_static(" AND status = 'delivering' AND lease_owner = ")
    .bind(claim.worker_id.as_str())
    .push_static(" AND lease_expires_at_ms = ")
    .bind(claim.lease_expires_at_ms)
    .build()
}

fn fail_statement(
    flavor: DbSqlFlavor,
    claim: &WorkspaceMessageDeliveryClaim,
    next_attempt_at_ms: i64,
    last_error: &str,
) -> DbStatement {
    update_builder(
        flavor,
        "UPDATE workspace_message_delivery_outbox SET status = CASE WHEN attempt_count >= \
         max_attempts THEN 'dead_letter' ELSE 'pending' END, next_attempt_at_ms = ",
    )
    .bind(next_attempt_at_ms)
    .push_static(", last_error = ")
    .bind(last_error)
    .push_static(", lease_owner = NULL, lease_expires_at_ms = NULL WHERE workspace_id = ")
    .bind(claim.message.workspace_id.as_str())
    .push_static(" AND bcs_message_id = ")
    .bind(claim.message.id.as_str())
    .push_static(" AND agent_id = ")
    .bind(claim.target.agent_id.as_str())
    .push_static(" AND status = 'delivering' AND lease_owner = ")
    .bind(claim.worker_id.as_str())
    .push_static(" AND lease_expires_at_ms = ")
    .bind(claim.lease_expires_at_ms)
    .push_static(" RETURNING status, attempt_count")
    .build()
}

fn update_builder(flavor: DbSqlFlavor, prefix: &'static str) -> DbStatementBuilder {
    DbStatementBuilder::new(flavor).push_static(prefix)
}

fn require_owned_lease(result: DbExecuteResult) -> Result<(), WorkspaceMessageStoreError> {
    if result.affected_rows == 1 {
        Ok(())
    } else {
        Err(WorkspaceMessageStoreError::DeliveryLeaseLost)
    }
}

fn delivery_target_from_row(
    row: &DbRow,
) -> Result<WorkspaceMessageDeliveryTarget, WorkspaceMessageStoreError> {
    Ok(WorkspaceMessageDeliveryTarget {
        agent_id: required_string(row, "agent_id")?,
        bot_uuid: required_string(row, "bot_uuid")?,
        display_name: row.get_string("display_name")?,
    })
}

fn required_string(row: &DbRow, column: &str) -> Result<String, WorkspaceMessageStoreError> {
    row.get_string(column)?
        .ok_or_else(|| WorkspaceMessageStoreError::InvalidRecord(format!("{column} is missing")))
}

fn required_i64(row: &DbRow, column: &str) -> Result<i64, WorkspaceMessageStoreError> {
    row.get_i64(column)?
        .ok_or_else(|| WorkspaceMessageStoreError::InvalidRecord(format!("{column} is missing")))
}

#[cfg(test)]
#[path = "message_delivery_sql_tests.rs"]
mod sql_tests;
