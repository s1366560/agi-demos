//! Durable, editor-authorized attention handling for Workspace Autonomy.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use thiserror::Error;

use crate::WorkspaceAutonomyScope;

mod resolution;

use resolution::{judge_resolution_steps, resolution_outcome, resolution_receipt_lookup};

const MAX_ATTENTION_ID_CHARS: usize = 384;
const MAX_IDEMPOTENCY_KEY_CHARS: usize = 256;
const MAX_SOURCE_ID_CHARS: usize = 191;
const MAX_REASON_CHARS: usize = 10_000;

/// Persistent attention inserted atomically with a Judge block or escalation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyAttentionWrite {
    pub attention_id: String,
    pub root_task_id: String,
    pub source_kind: String,
    pub source_id: String,
    pub reason: String,
    pub created_at_ms: i64,
}

/// One durable open attention projected to an authenticated Workspace member.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyAttentionRecord {
    pub attention_id: String,
    pub root_task_id: Option<String>,
    pub source_kind: String,
    pub source_id: String,
    pub reason: String,
    pub status: String,
    pub created_at_ms: i64,
}

/// Revision-guarded request to close one Judge-created attention.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyAttentionResolution {
    pub scope: WorkspaceAutonomyScope,
    pub actor_id: String,
    pub actor_is_superuser: bool,
    pub attention_id: String,
    pub expected_revision: u64,
    pub idempotency_key: String,
    pub request_hash: String,
    pub resolved_at_ms: i64,
}

/// Committed or replayed Judge-attention resolution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyAttentionResolutionOutcome {
    pub committed_revision: u64,
    pub outbox_id: String,
    pub receipt_id: String,
    pub replayed: bool,
}

/// Stable Autonomy attention persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyAttentionStoreError {
    #[error("invalid Workspace Autonomy attention request")]
    InvalidRequest,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Workspace Autonomy attention was not open or did not match its source")]
    Conflict,
    #[error("idempotency key was already used with a different attention request")]
    IdempotencyConflict,
    #[error("Workspace Autonomy attention receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace Autonomy attention is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite attention resolution and retry repository.
pub struct WorkspaceAutonomyAttentionStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyAttentionStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// List open attentions in stable creation order for one exact Workspace scope.
    pub async fn list_open(
        &self,
        scope: &WorkspaceAutonomyScope,
    ) -> Result<Vec<WorkspaceAutonomyAttentionRecord>, WorkspaceAutonomyAttentionStoreError> {
        validate_scope(scope)?;
        self.db
            .query(list_open_statement(self.flavor, scope))
            .await?
            .iter()
            .map(attention_from_row)
            .collect()
    }

    /// Read one exact open attention before selecting its structural retry operation.
    pub async fn open_attention(
        &self,
        scope: &WorkspaceAutonomyScope,
        attention_id: &str,
    ) -> Result<WorkspaceAutonomyAttentionRecord, WorkspaceAutonomyAttentionStoreError> {
        validate_scope(scope)?;
        validate_attention_id(attention_id)?;
        self.db
            .query(open_attention_statement(self.flavor, scope, attention_id))
            .await?
            .first()
            .map(attention_from_row)
            .transpose()?
            .ok_or(WorkspaceAutonomyAttentionStoreError::Conflict)
    }

    /// Resolve a Judge block/escalation after an editor has handled it.
    pub async fn resolve_judge_attention(
        &self,
        resolution: &WorkspaceAutonomyAttentionResolution,
    ) -> Result<WorkspaceAutonomyAttentionResolutionOutcome, WorkspaceAutonomyAttentionStoreError>
    {
        validate_judge_resolution(resolution)?;
        self.require_editor(
            &resolution.scope,
            resolution.actor_id.as_str(),
            resolution.actor_is_superuser,
        )
        .await?;
        if let Some(outcome) = self.read_resolution_receipt(resolution, true).await? {
            return Ok(outcome);
        }
        let results = match self
            .db
            .transaction(judge_resolution_steps(self.flavor, resolution)?)
            .await
        {
            Ok(results) => results,
            Err(DbError::TransactionExpectation { step_index: 0, .. }) => {
                return Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired);
            }
            Err(error)
                if error.is_duplicate_key()
                    || matches!(error, DbError::TransactionExpectation { step_index: 1, .. }) =>
            {
                self.require_editor(
                    &resolution.scope,
                    resolution.actor_id.as_str(),
                    resolution.actor_is_superuser,
                )
                .await?;
                if let Some(outcome) = self.read_resolution_receipt(resolution, true).await? {
                    return Ok(outcome);
                }
                return Err(WorkspaceAutonomyAttentionStoreError::Conflict);
            }
            Err(DbError::TransactionExpectation { .. }) => {
                return Err(WorkspaceAutonomyAttentionStoreError::Conflict);
            }
            Err(error) => return Err(error.into()),
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceAutonomyAttentionStoreError::IncompleteReceipt);
        };
        resolution_outcome(
            resolution,
            rows.first()
                .ok_or(WorkspaceAutonomyAttentionStoreError::IncompleteReceipt)?,
            false,
        )?
        .ok_or(WorkspaceAutonomyAttentionStoreError::IncompleteReceipt)
    }

    /// Atomically reopen the original dead-letter progression and resolve its attention.
    pub async fn retry_dead_letter(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        actor_is_superuser: bool,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
        validate_resolution(scope, actor_id, attention_id, retry_at_ms)?;
        self.execute_resolution(vec![
            DbTransactionStep::query_checked(
                editor_access_statement(self.flavor, scope, actor_id, actor_is_superuser),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                reset_dead_letter_statement(self.flavor, scope, attention_id, retry_at_ms),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                resolve_dead_letter_attention_statement(
                    self.flavor,
                    scope,
                    actor_id,
                    attention_id,
                    retry_at_ms,
                ),
                DbCountExpectation::exactly(1),
            ),
        ])
        .await
    }

    /// Atomically reopen a dead-letter autonomous bootstrap and resolve its attention.
    pub async fn retry_bootstrap_dead_letter(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        actor_is_superuser: bool,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
        validate_resolution(scope, actor_id, attention_id, retry_at_ms)?;
        self.execute_resolution(vec![
            DbTransactionStep::query_checked(
                editor_access_statement(self.flavor, scope, actor_id, actor_is_superuser),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                reset_bootstrap_dead_letter_statement(
                    self.flavor,
                    scope,
                    attention_id,
                    retry_at_ms,
                ),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                resolve_bootstrap_dead_letter_attention_statement(
                    self.flavor,
                    scope,
                    actor_id,
                    attention_id,
                    retry_at_ms,
                ),
                DbCountExpectation::exactly(1),
            ),
        ])
        .await
    }

    /// Atomically reopen the original dead-letter Task dispatch and resolve its attention.
    pub async fn retry_task_dispatch_dead_letter(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        actor_is_superuser: bool,
        attention_id: &str,
        retry_at_ms: i64,
    ) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
        validate_resolution(scope, actor_id, attention_id, retry_at_ms)?;
        self.execute_resolution(vec![
            DbTransactionStep::query_checked(
                editor_access_statement(self.flavor, scope, actor_id, actor_is_superuser),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                reset_task_dispatch_dead_letter_statement(
                    self.flavor,
                    scope,
                    attention_id,
                    retry_at_ms,
                ),
                DbCountExpectation::exactly(1),
            ),
            DbTransactionStep::execute_checked(
                resolve_task_dispatch_dead_letter_attention_statement(
                    self.flavor,
                    scope,
                    actor_id,
                    attention_id,
                    retry_at_ms,
                ),
                DbCountExpectation::exactly(1),
            ),
        ])
        .await
    }

    async fn execute_resolution(
        &self,
        steps: Vec<DbTransactionStep>,
    ) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
        match self.db.transaction(steps).await {
            Ok(_) => Ok(()),
            Err(DbError::TransactionExpectation { step_index: 0, .. }) => {
                Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired)
            }
            Err(DbError::TransactionExpectation { .. }) => {
                Err(WorkspaceAutonomyAttentionStoreError::Conflict)
            }
            Err(error) => Err(error.into()),
        }
    }

    async fn require_editor(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        actor_is_superuser: bool,
    ) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
        if self
            .db
            .query(editor_access_statement(
                self.flavor,
                scope,
                actor_id,
                actor_is_superuser,
            ))
            .await?
            .is_empty()
        {
            return Err(WorkspaceAutonomyAttentionStoreError::EditorAccessRequired);
        }
        Ok(())
    }

    async fn read_resolution_receipt(
        &self,
        resolution: &WorkspaceAutonomyAttentionResolution,
        replayed: bool,
    ) -> Result<
        Option<WorkspaceAutonomyAttentionResolutionOutcome>,
        WorkspaceAutonomyAttentionStoreError,
    > {
        self.db
            .query(resolution_receipt_lookup(self.flavor, resolution))
            .await?
            .first()
            .map(|row| resolution_outcome(resolution, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn validate_judge_resolution(
    resolution: &WorkspaceAutonomyAttentionResolution,
) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
    validate_resolution(
        &resolution.scope,
        resolution.actor_id.as_str(),
        resolution.attention_id.as_str(),
        resolution.resolved_at_ms,
    )?;
    if resolution.idempotency_key.trim().is_empty()
        || resolution.idempotency_key.trim() != resolution.idempotency_key
        || resolution.idempotency_key.chars().count() > MAX_IDEMPOTENCY_KEY_CHARS
        || resolution.request_hash.len() != 64
        || !resolution
            .request_hash
            .bytes()
            .all(|byte| byte.is_ascii_hexdigit())
    {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRequest);
    }
    Ok(())
}

fn validate_resolution(
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    occurred_at_ms: i64,
) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
    validate_scope(scope)?;
    validate_attention_id(attention_id)?;
    if actor_id.trim().is_empty() || occurred_at_ms < 0 {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRequest);
    }
    Ok(())
}

fn validate_attention_id(attention_id: &str) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
    if attention_id.trim().is_empty() || attention_id.chars().count() > MAX_ATTENTION_ID_CHARS {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRequest);
    }
    Ok(())
}

fn validate_scope(
    scope: &WorkspaceAutonomyScope,
) -> Result<(), WorkspaceAutonomyAttentionStoreError> {
    if [
        scope.tenant_id.as_str(),
        scope.project_id.as_str(),
        scope.workspace_id.as_str(),
    ]
    .iter()
    .any(|value| value.trim().is_empty())
    {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRequest);
    }
    Ok(())
}

fn list_open_statement(flavor: DbSqlFlavor, scope: &WorkspaceAutonomyScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT attention_id, root_task_id, source_kind, source_id, reason, status, \
             created_at_ms FROM workspace_autonomy_attentions WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND status = 'open' ORDER BY created_at_ms ASC, attention_id ASC")
        .build()
}

fn open_attention_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    attention_id: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT attention_id, root_task_id, source_kind, source_id, reason, status, \
             created_at_ms FROM workspace_autonomy_attentions WHERE attention_id = ",
        )
        .bind(attention_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND status = 'open'")
        .build()
}

fn attention_from_row(
    row: &DbRow,
) -> Result<WorkspaceAutonomyAttentionRecord, WorkspaceAutonomyAttentionStoreError> {
    let source_kind = required_string(row, "source_kind")?;
    if !matches!(
        source_kind.as_str(),
        "judge_block"
            | "judge_escalate"
            | "progression_dead_letter"
            | "bootstrap_dead_letter"
            | "task_dispatch_dead_letter"
    ) {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRecord(
            "source_kind",
        ));
    }
    let status = required_string(row, "status")?;
    if status != "open" {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRecord(
            "status",
        ));
    }
    let created_at_ms = row
        .get_i64("created_at_ms")?
        .filter(|value| *value >= 0)
        .ok_or(WorkspaceAutonomyAttentionStoreError::InvalidRecord(
            "created_at_ms",
        ))?;
    Ok(WorkspaceAutonomyAttentionRecord {
        attention_id: required_string(row, "attention_id")?,
        root_task_id: row.get_string("root_task_id")?,
        source_kind,
        source_id: required_string(row, "source_id")?,
        reason: required_string(row, "reason")?,
        status,
        created_at_ms,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyAttentionStoreError> {
    row.get_string(column)?
        .filter(|value| !value.trim().is_empty())
        .ok_or(WorkspaceAutonomyAttentionStoreError::InvalidRecord(column))
}

fn editor_access_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    actor_is_superuser: bool,
) -> DbStatement {
    if actor_is_superuser {
        return DbStatementBuilder::new(flavor)
            .push_static("SELECT workspace_id FROM workspace_profiles WHERE tenant_id = ")
            .bind(scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND deleted_at IS NULL")
            .build();
    }
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT p.workspace_id FROM workspace_profiles p JOIN workspace_members m ON \
             m.tenant_id = p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = \
             p.workspace_id WHERE p.tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND m.user_id = ")
        .bind(actor_id)
        .push_static(" AND m.role IN ('owner', 'editor', 'admin')")
        .build()
}

pub(crate) fn attention_insert_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    attention: &WorkspaceAutonomyAttentionWrite,
) -> Result<DbStatement, WorkspaceAutonomyAttentionStoreError> {
    if attention.attention_id.trim().is_empty()
        || attention.attention_id.chars().count() > MAX_ATTENTION_ID_CHARS
        || attention.root_task_id.trim().is_empty()
        || attention.source_id.trim().is_empty()
        || attention.source_id.chars().count() > MAX_SOURCE_ID_CHARS
        || !matches!(
            attention.source_kind.as_str(),
            "judge_block" | "judge_escalate"
        )
        || attention.reason.trim().is_empty()
        || attention.reason.chars().count() > MAX_REASON_CHARS
        || attention.created_at_ms < 0
    {
        return Err(WorkspaceAutonomyAttentionStoreError::InvalidRequest);
    }
    Ok(DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_autonomy_attentions (attention_id, tenant_id, project_id, \
             workspace_id, root_task_id, source_kind, source_id, reason, status, created_at_ms) \
             VALUES (",
        )
        .bind(attention.attention_id.as_str())
        .push_static(", ")
        .bind(scope.tenant_id.as_str())
        .push_static(", ")
        .bind(scope.project_id.as_str())
        .push_static(", ")
        .bind(scope.workspace_id.as_str())
        .push_static(", ")
        .bind(attention.root_task_id.as_str())
        .push_static(", ")
        .bind(attention.source_kind.as_str())
        .push_static(", ")
        .bind(attention.source_id.as_str())
        .push_static(", ")
        .bind(attention.reason.as_str())
        .push_static(", 'open', ")
        .bind(attention.created_at_ms)
        .push_static(")")
        .build())
}

fn resolve_judge_attention_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    resolved_at_ms: i64,
) -> DbStatement {
    resolution_statement(flavor, scope, actor_id, attention_id, resolved_at_ms)
        .push_static(" AND source_kind IN ('judge_block', 'judge_escalate')")
        .build()
}

fn resolve_dead_letter_attention_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    resolved_at_ms: i64,
) -> DbStatement {
    resolution_statement(flavor, scope, actor_id, attention_id, resolved_at_ms)
        .push_static(" AND source_kind = 'progression_dead_letter'")
        .build()
}

fn resolve_bootstrap_dead_letter_attention_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    resolved_at_ms: i64,
) -> DbStatement {
    resolution_statement(flavor, scope, actor_id, attention_id, resolved_at_ms)
        .push_static(" AND source_kind = 'bootstrap_dead_letter'")
        .build()
}

fn resolve_task_dispatch_dead_letter_attention_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    resolved_at_ms: i64,
) -> DbStatement {
    resolution_statement(flavor, scope, actor_id, attention_id, resolved_at_ms)
        .push_static(" AND source_kind = 'task_dispatch_dead_letter'")
        .build()
}

fn resolution_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    actor_id: &str,
    attention_id: &str,
    resolved_at_ms: i64,
) -> DbStatementBuilder {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_attentions SET status = 'resolved', resolved_at_ms = ",
        )
        .bind(resolved_at_ms)
        .push_static(", resolved_by_actor_id = ")
        .bind(actor_id)
        .push_static(" WHERE attention_id = ")
        .bind(attention_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND status = 'open'")
}

fn reset_dead_letter_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    attention_id: &str,
    retry_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_progression_outbox SET status = 'pending', \
             attempt_count = 0, next_attempt_at_ms = ",
        )
        .bind(retry_at_ms)
        .push_static(
            ", lease_owner = NULL, lease_expires_at_ms = NULL, execution_task_id = NULL, \
             last_error = NULL, completed_at_ms = NULL WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(
            " AND status = 'dead_letter' AND progression_id = (SELECT source_id FROM \
             workspace_autonomy_attentions WHERE attention_id = ",
        )
        .bind(attention_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND source_kind = 'progression_dead_letter' AND status = 'open')")
        .build()
}

fn reset_bootstrap_dead_letter_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    attention_id: &str,
    retry_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_autonomy_bootstrap_outbox SET status = 'pending', \
             attempt_count = 0, next_attempt_at_ms = ",
        )
        .bind(retry_at_ms)
        .push_static(
            ", lease_owner = NULL, lease_expires_at_ms = NULL, objective_id = NULL, \
             root_task_id = NULL, last_error = NULL, completed_at_ms = NULL WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(
            " AND status = 'dead_letter' AND bootstrap_id = (SELECT source_id FROM \
             workspace_autonomy_attentions WHERE attention_id = ",
        )
        .bind(attention_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND source_kind = 'bootstrap_dead_letter' AND status = 'open')")
        .build()
}

fn reset_task_dispatch_dead_letter_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    attention_id: &str,
    retry_at_ms: i64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "UPDATE workspace_task_dispatch_outbox SET status = 'pending', attempt_count = 0, \
             next_attempt_at_ms = ",
        )
        .bind(retry_at_ms)
        .push_static(
            ", lease_owner = NULL, lease_expires_at_ms = NULL, last_error = NULL, \
             delivered_at_ms = NULL WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(
            " AND status = 'dead_letter' AND dispatch_id = (SELECT source_id FROM \
             workspace_autonomy_attentions WHERE attention_id = ",
        )
        .bind(attention_id)
        .push_static(" AND tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND source_kind = 'task_dispatch_dead_letter' AND status = 'open')")
        .build()
}

#[cfg(test)]
mod tests;
