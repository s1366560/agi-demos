//! Atomic persistence for structured Workspace Autonomy tick verdicts.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::autonomy_attention::attention_insert_statement;
use crate::autonomy_judgment::{audit_complete_statement, claim_apply_statement};

/// Tenant/project/workspace scope for one Autonomy operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Full structured Agent tool-call audit persisted with the verdict.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAutonomyJudgmentAudit {
    pub audit_id: String,
    pub agent_id: String,
    pub tool_name: String,
    pub input: Value,
    pub output: Value,
    pub rationale: String,
    pub latency_ms: u64,
    pub status: String,
    pub error_detail: Option<String>,
    pub created_at: String,
}

/// Active Workspace Agent binding supplied to the structured Autonomy Judge.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAutonomyAgentBinding {
    pub binding_id: String,
    pub agent_id: String,
    pub display_name: Option<String>,
    pub description: Option<String>,
    pub status: String,
    pub config: Value,
}

/// Durable continuation selected by the Judge and inserted with the tick.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceAutonomyProgressionWrite {
    pub progression_id: String,
    pub root_task_id: String,
    pub judge_agent_id: String,
    pub workspace_agent_binding_id: String,
    pub task_title: String,
    pub task_description: String,
    pub created_at_ms: i64,
}

/// Complete Autonomy tick mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAutonomyMutation {
    pub tick_id: String,
    pub scope: WorkspaceAutonomyScope,
    pub actor_id: String,
    pub actor_is_superuser: bool,
    pub idempotency_key: String,
    pub request_hash: String,
    pub expected_revision: u64,
    pub root_task_id: Option<String>,
    pub verdict: String,
    pub reason: String,
    pub force: bool,
    pub judgment: Option<WorkspaceAutonomyJudgmentAudit>,
    pub judgment_apply: Option<crate::WorkspaceAutonomyJudgmentApply>,
    pub progression: Option<WorkspaceAutonomyProgressionWrite>,
    pub attention: Option<crate::WorkspaceAutonomyAttentionWrite>,
    pub response: Value,
    pub created_at: String,
}

/// Committed or replayed Autonomy tick outcome.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceAutonomyMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub receipt_id: String,
    pub replayed: bool,
}

/// Stable Autonomy persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceAutonomyStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Workspace Autonomy tick conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace Autonomy receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace Autonomy record is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite Autonomy repository.
pub struct WorkspaceAutonomyStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceAutonomyStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require editor authority before exposing candidate evidence to the Judge.
    pub async fn require_editor(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        actor_is_superuser: bool,
    ) -> Result<(), WorkspaceAutonomyStoreError> {
        let probe = WorkspaceAutonomyMutation {
            tick_id: String::new(),
            scope: scope.clone(),
            actor_id: actor_id.to_string(),
            actor_is_superuser,
            idempotency_key: String::new(),
            request_hash: String::new(),
            expected_revision: 0,
            root_task_id: None,
            verdict: String::new(),
            reason: String::new(),
            force: false,
            judgment: None,
            judgment_apply: None,
            progression: None,
            attention: None,
            response: Value::Null,
            created_at: String::new(),
        };
        if self
            .db
            .query(workspace_exists(self.flavor, scope))
            .await?
            .is_empty()
        {
            return Err(WorkspaceAutonomyStoreError::NotFound);
        }
        if self
            .db
            .query(editor_access_check(self.flavor, &probe))
            .await?
            .is_empty()
        {
            return Err(WorkspaceAutonomyStoreError::EditorAccessRequired);
        }
        Ok(())
    }

    /// Read the current Workspace revision.
    pub async fn revision(
        &self,
        scope: &WorkspaceAutonomyScope,
    ) -> Result<u64, WorkspaceAutonomyStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .build(),
            )
            .await?;
        let row = rows.first().ok_or(WorkspaceAutonomyStoreError::NotFound)?;
        let revision = row
            .get_i64("revision")?
            .ok_or(WorkspaceAutonomyStoreError::InvalidRecord("revision"))?;
        u64::try_from(revision).map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("revision"))
    }

    /// Read the newest persisted tick timestamp for one root Task.
    pub async fn last_tick_at(
        &self,
        scope: &WorkspaceAutonomyScope,
        root_task_id: &str,
    ) -> Result<Option<String>, WorkspaceAutonomyStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT created_at FROM workspace_autonomy_ticks WHERE tenant_id = ",
                    )
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .push_static(" AND root_task_id = ")
                    .bind(root_task_id)
                    .push_static(" ORDER BY created_at DESC, tick_id ASC LIMIT 1")
                    .build(),
            )
            .await?;
        rows.first()
            .map(|row| required_string(row, "created_at"))
            .transpose()
    }

    /// List active Agent bindings as bounded structured Judge candidates.
    pub async fn active_agent_bindings(
        &self,
        scope: &WorkspaceAutonomyScope,
        limit: i64,
    ) -> Result<Vec<WorkspaceAutonomyAgentBinding>, WorkspaceAutonomyStoreError> {
        if !(1..=500).contains(&limit) {
            return Err(WorkspaceAutonomyStoreError::InvalidRecord(
                "agent binding limit",
            ));
        }
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT binding_id, agent_id, display_name, description, status, \
                         config_json FROM workspace_agent_bindings WHERE tenant_id = ",
                    )
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .push_static(
                        " AND is_active = TRUE ORDER BY created_at ASC, binding_id ASC LIMIT ",
                    )
                    .bind(limit)
                    .build(),
            )
            .await?;
        rows.iter().map(agent_binding_from_row).collect()
    }

    /// List open root Tasks that have no pending continuation or unfinished execution Task.
    pub async fn eligible_root_task_ids(
        &self,
        scope: &WorkspaceAutonomyScope,
        limit: i64,
    ) -> Result<Vec<String>, WorkspaceAutonomyStoreError> {
        if !(1..=500).contains(&limit) {
            return Err(WorkspaceAutonomyStoreError::InvalidRecord(
                "eligible root limit",
            ));
        }
        self.db
            .query(eligible_root_task_ids_statement(self.flavor, scope, limit))
            .await?
            .iter()
            .map(|row| required_string(row, "task_id"))
            .collect()
    }

    /// Replay one committed idempotency receipt before invoking the external Judge.
    pub async fn replay(
        &self,
        scope: &WorkspaceAutonomyScope,
        actor_id: &str,
        idempotency_key: &str,
        request_hash: &str,
    ) -> Result<Option<WorkspaceAutonomyMutationOutcome>, WorkspaceAutonomyStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT r.receipt_id, r.request_hash, r.committed_revision, \
                         r.response_json, o.outbox_id FROM workspace_mutation_receipts r \
                         LEFT JOIN workspace_outbox o ON o.tenant_id = r.tenant_id \
                          AND o.project_id = r.project_id AND o.workspace_id = r.workspace_id \
                          AND o.idempotency_key = r.idempotency_key WHERE r.tenant_id = ",
                    )
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND r.project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND r.workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .push_static(" AND r.actor_id = ")
                    .bind(actor_id)
                    .push_static(" AND r.idempotency_key = ")
                    .bind(idempotency_key)
                    .build(),
            )
            .await?;
        let Some(row) = rows.first() else {
            return Ok(None);
        };
        if required_string(row, "request_hash")? != request_hash {
            return Err(WorkspaceAutonomyStoreError::IdempotencyConflict);
        }
        let committed_revision = row
            .get_i64("committed_revision")?
            .ok_or(WorkspaceAutonomyStoreError::IncompleteReceipt)?;
        let response = serde_json::from_str(&required_string(row, "response_json")?)
            .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("response_json"))?;
        Ok(Some(WorkspaceAutonomyMutationOutcome {
            committed_revision: u64::try_from(committed_revision)
                .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("committed_revision"))?,
            response,
            outbox_id: required_string(row, "outbox_id")?,
            receipt_id: required_string(row, "receipt_id")?,
            replayed: true,
        }))
    }

    /// Execute one atomic Autonomy tick or replay its receipt.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceAutonomyMutation,
    ) -> Result<WorkspaceAutonomyMutationOutcome, WorkspaceAutonomyStoreError> {
        let lookup = receipt_lookup(self.flavor, mutation);
        if let Some(outcome) = self.read_receipt(mutation, lookup.clone(), true).await? {
            return Ok(outcome);
        }
        let results = match self
            .db
            .transaction(mutation_steps(self.flavor, mutation)?)
            .await
        {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_receipt(mutation, lookup, true).await?
                {
                    return Ok(outcome);
                }
                if matches!(error, DbError::TransactionExpectation { .. })
                    || error.is_duplicate_key()
                {
                    return Err(WorkspaceAutonomyStoreError::Conflict);
                }
                return Err(error.into());
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceAutonomyStoreError::IncompleteReceipt);
        };
        receipt_outcome(
            mutation,
            rows.first()
                .ok_or(WorkspaceAutonomyStoreError::IncompleteReceipt)?,
            false,
        )?
        .ok_or(WorkspaceAutonomyStoreError::IncompleteReceipt)
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceAutonomyMutation,
        statement: DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceAutonomyMutationOutcome>, WorkspaceAutonomyStoreError> {
        self.db
            .query(statement)
            .await?
            .first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn eligible_root_task_ids_statement(
    flavor: DbSqlFlavor,
    scope: &WorkspaceAutonomyScope,
    limit: i64,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT root.task_id FROM workspace_tasks root WHERE root.tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND root.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND root.workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(
            " AND root.archived_at IS NULL AND root.status NOT IN ('done', 'blocked') AND ",
        );
    let builder = match flavor {
        DbSqlFlavor::Postgres => {
            builder.push_static("root.metadata_json ->> 'task_role' = 'goal_root'")
        }
        DbSqlFlavor::Sqlite => {
            builder.push_static("json_extract(root.metadata_json, '$.task_role') = 'goal_root'")
        }
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    let builder = builder.push_static(
        " AND NOT EXISTS (SELECT 1 FROM workspace_autonomy_attentions attention WHERE \
         attention.tenant_id = root.tenant_id AND attention.project_id = root.project_id AND \
         attention.workspace_id = root.workspace_id AND attention.root_task_id = root.task_id AND \
         attention.status = 'open') AND NOT EXISTS (SELECT 1 FROM \
         workspace_autonomy_progression_outbox progression \
         WHERE progression.tenant_id = root.tenant_id AND progression.project_id = \
         root.project_id AND progression.workspace_id = root.workspace_id AND \
         progression.root_task_id = root.task_id AND progression.status IN ('pending', \
         'processing', 'dead_letter')) AND NOT EXISTS (SELECT 1 FROM workspace_tasks execution \
         WHERE execution.tenant_id = root.tenant_id AND execution.project_id = root.project_id AND \
         execution.workspace_id = root.workspace_id AND execution.archived_at IS NULL AND \
         execution.status NOT IN ('done', 'blocked') AND ",
    );
    let builder = match flavor {
        DbSqlFlavor::Postgres => builder.push_static(
            "execution.metadata_json ->> 'task_role' = 'execution_task' AND \
             execution.metadata_json ->> 'root_goal_task_id' = root.task_id",
        ),
        DbSqlFlavor::Sqlite => builder.push_static(
            "json_extract(execution.metadata_json, '$.task_role') = 'execution_task' AND \
             json_extract(execution.metadata_json, '$.root_goal_task_id') = root.task_id",
        ),
        DbSqlFlavor::Mysql => builder.push_static("1 = 0"),
    };
    builder
        .push_static(") ORDER BY root.created_at ASC, root.task_id ASC LIMIT ")
        .bind(limit)
        .build()
}

fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceAutonomyMutation,
) -> Result<Vec<DbTransactionStep>, WorkspaceAutonomyStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceAutonomyStoreError::Conflict)?;
    let receipt_id = deterministic_id("autonomy-receipt", mutation);
    let outbox_id = deterministic_id("autonomy-outbox", mutation);
    let mut steps = Vec::with_capacity(12);
    steps.push(DbTransactionStep::query_checked(
        editor_access_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_insert(flavor, mutation, receipt_id.as_str()),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        revision_check(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        tick_insert(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    if let Some(attention) = &mutation.attention {
        steps.push(DbTransactionStep::execute_checked(
            attention_insert_statement(flavor, &mutation.scope, attention)
                .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("attention"))?,
            DbCountExpectation::exactly(1),
        ));
    }
    if let Some(progression) = &mutation.progression {
        steps.push(DbTransactionStep::execute_checked(
            progression_insert(flavor, mutation, progression),
            DbCountExpectation::exactly(1),
        ));
    }
    steps.push(DbTransactionStep::execute_checked(
        authority_cas(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    if let Some(apply) = &mutation.judgment_apply {
        steps.push(DbTransactionStep::execute_checked(
            claim_apply_statement(flavor, apply),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::execute_checked(
            audit_complete_statement(flavor, apply.audit_id.as_str()),
            DbCountExpectation::exactly(1),
        ));
    }
    steps.push(DbTransactionStep::execute_checked(
        outbox_insert(flavor, mutation, outbox_id.as_str(), committed_revision),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::execute_checked(
        receipt_finalize(flavor, mutation, receipt_id.as_str(), committed_revision),
        DbCountExpectation::exactly(1),
    ));
    steps.push(DbTransactionStep::query_checked(
        receipt_lookup(flavor, mutation),
        DbCountExpectation::exactly(1),
    ));
    Ok(steps)
}

fn editor_access_check(flavor: DbSqlFlavor, mutation: &WorkspaceAutonomyMutation) -> DbStatement {
    if mutation.actor_is_superuser {
        return workspace_exists(flavor, &mutation.scope);
    }
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT p.workspace_id FROM workspace_profiles p JOIN workspace_members m \
             ON m.tenant_id = p.tenant_id AND m.project_id = p.project_id \
             AND m.workspace_id = p.workspace_id WHERE p.tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND m.user_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND m.role IN ('owner', 'editor', 'admin')")
        .build()
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceAutonomyScope) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT workspace_id FROM workspace_profiles WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND deleted_at IS NULL")
        .build()
}

fn receipt_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceAutonomyMutation,
    receipt_id: &str,
) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, \
             workspace_id, actor_id, contract_version, surface, action, idempotency_key, \
             request_hash, expected_revision) VALUES (",
        )
        .bind(receipt_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(mutation.actor_id.as_str())
        .push_static(", 'v1', 'autonomy', 'tick', ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(", ")
        .bind(mutation.request_hash.as_str())
        .push_static(", ")
        .bind(mutation.expected_revision)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn receipt_lookup(flavor: DbSqlFlavor, mutation: &WorkspaceAutonomyMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT receipt_id, request_hash, committed_revision, response_json FROM \
             workspace_mutation_receipts WHERE tenant_id = ",
        )
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(mutation.actor_id.as_str())
        .push_static(" AND idempotency_key = ")
        .bind(mutation.idempotency_key.as_str())
        .build()
}

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceAutonomyMutation) -> DbStatement {
    let builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision);
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static(" FOR UPDATE").build()
    } else {
        builder.build()
    }
}

fn tick_insert(flavor: DbSqlFlavor, mutation: &WorkspaceAutonomyMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_autonomy_ticks (tick_id, tenant_id, project_id, workspace_id, \
             root_task_id, actor_id, force, verdict, reason, judge_audit_id, created_at) VALUES (",
        )
        .bind(mutation.tick_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(mutation.root_task_id.clone())
        .push_static(", ")
        .bind(mutation.actor_id.as_str())
        .push_static(", ")
        .bind(mutation.force)
        .push_static(", ")
        .bind(mutation.verdict.as_str())
        .push_static(", ")
        .bind(mutation.reason.as_str())
        .push_static(", ")
        .bind(
            mutation
                .judgment
                .as_ref()
                .map(|audit| audit.audit_id.clone()),
        )
        .push_static(", ")
        .bind(mutation.created_at.as_str())
        .push_static(")")
        .build()
}

fn progression_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceAutonomyMutation,
    progression: &WorkspaceAutonomyProgressionWrite,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_autonomy_progression_outbox (progression_id, tick_id, \
             tenant_id, project_id, workspace_id, root_task_id, actor_id, judge_agent_id, \
             workspace_agent_binding_id, task_title, task_description, status, attempt_count, \
             max_attempts, next_attempt_at_ms, lease_generation, created_at_ms) VALUES (",
        )
        .bind(progression.progression_id.as_str())
        .push_static(", ")
        .bind(mutation.tick_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", ")
        .bind(progression.root_task_id.as_str())
        .push_static(", ")
        .bind(mutation.actor_id.as_str())
        .push_static(", ")
        .bind(progression.judge_agent_id.as_str())
        .push_static(", ")
        .bind(progression.workspace_agent_binding_id.as_str())
        .push_static(", ")
        .bind(progression.task_title.as_str())
        .push_static(", ")
        .bind(progression.task_description.as_str())
        .push_static(", 'pending', 0, 8, 0, 0, ")
        .bind(progression.created_at_ms)
        .push_static(")")
        .build()
}

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceAutonomyMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_authorities SET revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND revision = ")
        .bind(mutation.expected_revision)
        .build()
}

fn outbox_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceAutonomyMutation,
    outbox_id: &str,
    committed_revision: u64,
) -> DbStatement {
    let metadata = serde_json::json!({
        "request_hash": &mutation.request_hash,
        "surface": "autonomy",
        "tick_id": &mutation.tick_id,
    });
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, \
             aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, \
             metadata_json, correlation_id, idempotency_key) VALUES (",
        )
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.scope.tenant_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.project_id.as_str())
        .push_static(", ")
        .bind(mutation.scope.workspace_id.as_str())
        .push_static(", 'workspace_autonomy', ")
        .bind(mutation.tick_id.as_str())
        .push_static(", 'workspace_autonomy_tick_judged', ")
        .bind(format!("workspace:{}", mutation.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(mutation.response.to_string())
        .push_static(", ")
        .bind(metadata.to_string())
        .push_static(", ")
        .bind(outbox_id)
        .push_static(", ")
        .bind(mutation.idempotency_key.as_str())
        .push_static(")")
        .build()
}

fn receipt_finalize(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceAutonomyMutation,
    receipt_id: &str,
    committed_revision: u64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
        .bind(committed_revision)
        .push_static(", response_json = ")
        .bind(mutation.response.to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(" AND request_hash = ")
        .bind(mutation.request_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

fn receipt_outcome(
    mutation: &WorkspaceAutonomyMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceAutonomyMutationOutcome>, WorkspaceAutonomyStoreError> {
    if required_string(row, "request_hash")? != mutation.request_hash {
        return Err(WorkspaceAutonomyStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Ok(None);
    };
    let response = serde_json::from_str(&required_string(row, "response_json")?)
        .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("response_json"))?;
    Ok(Some(WorkspaceAutonomyMutationOutcome {
        committed_revision: u64::try_from(committed_revision)
            .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("committed_revision"))?,
        response,
        outbox_id: deterministic_id("autonomy-outbox", mutation),
        receipt_id: required_string(row, "receipt_id")?,
        replayed,
    }))
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceAutonomyStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceAutonomyStoreError::InvalidRecord(column))
}

fn agent_binding_from_row(
    row: &DbRow,
) -> Result<WorkspaceAutonomyAgentBinding, WorkspaceAutonomyStoreError> {
    let config: Value = serde_json::from_str(&required_string(row, "config_json")?)
        .map_err(|_| WorkspaceAutonomyStoreError::InvalidRecord("config_json"))?;
    if !config.is_object() {
        return Err(WorkspaceAutonomyStoreError::InvalidRecord("config_json"));
    }
    Ok(WorkspaceAutonomyAgentBinding {
        binding_id: required_string(row, "binding_id")?,
        agent_id: required_string(row, "agent_id")?,
        display_name: row.get_string("display_name")?,
        description: row.get_string("description")?,
        status: required_string(row, "status")?,
        config,
    })
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceAutonomyMutation) -> String {
    let mut digest = Sha256::new();
    for part in [
        namespace,
        mutation.scope.tenant_id.as_str(),
        mutation.scope.project_id.as_str(),
        mutation.scope.workspace_id.as_str(),
        mutation.actor_id.as_str(),
        mutation.idempotency_key.as_str(),
        mutation.request_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}
