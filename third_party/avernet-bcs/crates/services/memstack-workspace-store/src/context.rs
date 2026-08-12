//! Dialect-aware Workspace Context reads, CAS transitions, judgment audits, and outbox writes.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use serde_json::Value;
use thiserror::Error;

/// One persisted active Context projection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextSnapshot {
    pub user_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub revision: u64,
    pub updated_at: String,
}

/// Current Context plus its still-active Project membership role.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextAccessSnapshot {
    pub context: WorkspaceContextSnapshot,
    pub membership_role: String,
}

/// One active mirrored Project membership eligible for Context selection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextCandidateSnapshot {
    pub tenant_id: String,
    pub project_id: String,
    pub membership_role: String,
}

/// Idempotent explicit-switch event used as its durable receipt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceContextEventReceipt {
    pub tenant_id: String,
    pub project_id: String,
    pub revision: u64,
    pub request_hash: String,
    pub created_at: String,
}

/// Context transition shape selected by the application service.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkspaceContextTransitionKind {
    Initialize,
    Repair,
    Switch,
}

/// One auditable Agent judgment record.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceContextAuditRecord {
    pub audit_id: String,
    pub user_id: String,
    pub tenant_id: Option<String>,
    pub project_id: Option<String>,
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

/// Complete atomic Context transition input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceContextTransition {
    pub kind: WorkspaceContextTransitionKind,
    pub user_id: String,
    pub actor_api_key_id: Option<String>,
    pub previous: Option<WorkspaceContextSnapshot>,
    pub selected: WorkspaceContextCandidateSnapshot,
    pub committed_revision: u64,
    pub idempotency_key: String,
    pub request_hash: String,
    pub event_id: Option<String>,
    pub outbox_id: String,
    pub event_type: String,
    pub payload: Value,
    pub metadata: Value,
    pub audit: Option<WorkspaceContextAuditRecord>,
    pub persisted_at: String,
}

/// Invalid or unavailable Workspace Context persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceContextStoreError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("Workspace Context is missing required data: {0}")]
    InvalidField(&'static str),

    #[error("Workspace Context revision is negative")]
    NegativeRevision,

    #[error("Workspace Context membership is unavailable")]
    MembershipUnavailable,

    #[error("Workspace Context revision changed")]
    RevisionChanged,

    #[error("Workspace Context transition conflicts with persisted state")]
    TransitionConflict,

    #[error("Workspace Context transaction returned an invalid result")]
    InvalidTransactionResult,
}

/// Read-side and atomic transition store for PostgreSQL and SQLite.
pub struct WorkspaceContextStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceContextStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Read the active Context only when its mirrored membership remains valid.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_accessible(
        &self,
        user_id: &str,
    ) -> Result<Option<WorkspaceContextAccessSnapshot>, WorkspaceContextStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT c.user_id, c.tenant_id, c.project_id, c.revision, c.updated_at, \
                         m.role AS membership_role FROM workspace_contexts c JOIN \
                         project_principal_memberships m ON m.tenant_id = c.tenant_id AND \
                         m.project_id = c.project_id AND m.user_id = c.user_id WHERE c.user_id = ",
                    )
                    .bind(user_id)
                    .push_static(" AND m.is_active = TRUE")
                    .build(),
            )
            .await?;
        rows.first().map(access_from_row).transpose()
    }

    /// Read the Context even when its selected membership became inactive.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_current(
        &self,
        user_id: &str,
    ) -> Result<Option<WorkspaceContextSnapshot>, WorkspaceContextStoreError> {
        let rows = self.db.query(self.context_select(user_id)).await?;
        rows.first().map(context_from_row).transpose()
    }

    /// List every active mirrored Project membership in structural ID order.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn list_candidates(
        &self,
        user_id: &str,
    ) -> Result<Vec<WorkspaceContextCandidateSnapshot>, WorkspaceContextStoreError> {
        self.db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT tenant_id, project_id, role AS membership_role FROM \
                         project_principal_memberships WHERE user_id = ",
                    )
                    .bind(user_id)
                    .push_static(" AND is_active = TRUE ORDER BY tenant_id, project_id")
                    .build(),
            )
            .await?
            .iter()
            .map(candidate_from_row)
            .collect()
    }

    /// Return whether the principal has any active Project in one tenant.
    ///
    /// # Errors
    ///
    /// Returns a database error.
    pub async fn has_tenant_membership(
        &self,
        user_id: &str,
        tenant_id: &str,
    ) -> Result<bool, WorkspaceContextStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT user_id FROM project_principal_memberships WHERE user_id = ",
                    )
                    .bind(user_id)
                    .push_static(" AND tenant_id = ")
                    .bind(tenant_id)
                    .push_static(" AND is_active = TRUE LIMIT 1")
                    .build(),
            )
            .await?;
        Ok(!rows.is_empty())
    }

    /// Read one exact active candidate.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_candidate(
        &self,
        user_id: &str,
        tenant_id: &str,
        project_id: &str,
    ) -> Result<Option<WorkspaceContextCandidateSnapshot>, WorkspaceContextStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT tenant_id, project_id, role AS membership_role FROM \
                         project_principal_memberships WHERE user_id = ",
                    )
                    .bind(user_id)
                    .push_static(" AND tenant_id = ")
                    .bind(tenant_id)
                    .push_static(" AND project_id = ")
                    .bind(project_id)
                    .push_static(" AND is_active = TRUE")
                    .build(),
            )
            .await?;
        rows.first().map(candidate_from_row).transpose()
    }

    /// Read a prior switch event by user-scoped idempotency key.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_event(
        &self,
        user_id: &str,
        idempotency_key: &str,
    ) -> Result<Option<WorkspaceContextEventReceipt>, WorkspaceContextStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT to_tenant_id, to_project_id, revision, request_hash, created_at \
                         FROM workspace_context_events WHERE user_id = ",
                    )
                    .bind(user_id)
                    .push_static(" AND idempotency_key = ")
                    .bind(idempotency_key)
                    .build(),
            )
            .await?;
        rows.first().map(event_from_row).transpose()
    }

    /// Atomically persist Context CAS, optional event/Judge audit, and durable outbox.
    ///
    /// # Errors
    ///
    /// Returns structured membership, revision, domain, or database failures.
    pub async fn transition(
        &self,
        transition: &WorkspaceContextTransition,
    ) -> Result<WorkspaceContextSnapshot, WorkspaceContextStoreError> {
        let mut steps = Vec::with_capacity(6);
        let membership_step = steps.len();
        steps.push(DbTransactionStep::query_checked(
            self.membership_check(transition),
            DbCountExpectation::exactly(1),
        ));
        let context_step = steps.len();
        steps.push(DbTransactionStep::execute_checked(
            self.context_write(transition),
            DbCountExpectation::exactly(1),
        ));
        if transition.kind != WorkspaceContextTransitionKind::Initialize {
            steps.push(DbTransactionStep::execute_checked(
                self.event_insert(transition)?,
                DbCountExpectation::exactly(1),
            ));
        }
        if let Some(audit) = &transition.audit {
            steps.push(DbTransactionStep::execute_checked(
                self.audit_insert(audit),
                DbCountExpectation::exactly(1),
            ));
        }
        steps.push(DbTransactionStep::execute_checked(
            self.outbox_insert(transition),
            DbCountExpectation::exactly(1),
        ));
        steps.push(DbTransactionStep::query_checked(
            self.context_select(&transition.user_id),
            DbCountExpectation::exactly(1),
        ));

        let results =
            self.db.transaction(steps).await.map_err(|error| {
                classify_transaction_error(error, membership_step, context_step)
            })?;
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceContextStoreError::InvalidTransactionResult);
        };
        let Some(row) = rows.first() else {
            return Err(WorkspaceContextStoreError::InvalidTransactionResult);
        };
        context_from_row(row)
    }

    /// Persist a failed external judgment audit without changing Context.
    ///
    /// # Errors
    ///
    /// Returns a database error or a conflicting audit identifier.
    pub async fn record_audit(
        &self,
        audit: &WorkspaceContextAuditRecord,
    ) -> Result<(), WorkspaceContextStoreError> {
        let result = self.db.execute(self.audit_insert(audit)).await?;
        if result.affected_rows != 1 {
            return Err(WorkspaceContextStoreError::TransitionConflict);
        }
        Ok(())
    }

    fn context_select(&self, user_id: &str) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT user_id, tenant_id, project_id, revision, updated_at FROM \
                 workspace_contexts WHERE user_id = ",
            )
            .bind(user_id)
            .build()
    }

    fn membership_check(&self, transition: &WorkspaceContextTransition) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static("SELECT user_id FROM project_principal_memberships WHERE user_id = ")
            .bind(transition.user_id.as_str())
            .push_static(" AND tenant_id = ")
            .bind(transition.selected.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(transition.selected.project_id.as_str())
            .push_static(" AND is_active = TRUE")
            .build()
    }

    fn context_write(&self, transition: &WorkspaceContextTransition) -> DbStatement {
        if let Some(previous) = &transition.previous {
            return DbStatementBuilder::new(self.flavor)
                .push_static("UPDATE workspace_contexts SET tenant_id = ")
                .bind(transition.selected.tenant_id.as_str())
                .push_static(", project_id = ")
                .bind(transition.selected.project_id.as_str())
                .push_static(", revision = ")
                .bind(transition.committed_revision)
                .push_static(", updated_at = ")
                .bind(transition.persisted_at.as_str())
                .push_static(" WHERE user_id = ")
                .bind(transition.user_id.as_str())
                .push_static(" AND tenant_id = ")
                .bind(previous.tenant_id.as_str())
                .push_static(" AND project_id = ")
                .bind(previous.project_id.as_str())
                .push_static(" AND revision = ")
                .bind(previous.revision)
                .build();
        }
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_contexts (user_id, tenant_id, project_id, revision, \
                 updated_at) SELECT ",
            )
            .bind(transition.user_id.as_str())
            .push_static(", ")
            .bind(transition.selected.tenant_id.as_str())
            .push_static(", ")
            .bind(transition.selected.project_id.as_str())
            .push_static(", ")
            .bind(transition.committed_revision)
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(" WHERE NOT EXISTS (SELECT 1 FROM workspace_contexts WHERE user_id = ")
            .bind(transition.user_id.as_str())
            .push_static(")")
            .build()
    }

    fn event_insert(
        &self,
        transition: &WorkspaceContextTransition,
    ) -> Result<DbStatement, WorkspaceContextStoreError> {
        let event_id = transition
            .event_id
            .as_deref()
            .ok_or(WorkspaceContextStoreError::InvalidField("event_id"))?;
        Ok(DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_context_events (event_id, user_id, actor_api_key_id, \
                 from_tenant_id, from_project_id, to_tenant_id, to_project_id, revision, \
                 idempotency_key, request_hash, value_json, created_at) VALUES (",
            )
            .bind(event_id)
            .push_static(", ")
            .bind(transition.user_id.as_str())
            .push_static(", ")
            .bind(transition.actor_api_key_id.clone())
            .push_static(", ")
            .bind(
                transition
                    .previous
                    .as_ref()
                    .map(|context| context.tenant_id.clone()),
            )
            .push_static(", ")
            .bind(
                transition
                    .previous
                    .as_ref()
                    .map(|context| context.project_id.clone()),
            )
            .push_static(", ")
            .bind(transition.selected.tenant_id.as_str())
            .push_static(", ")
            .bind(transition.selected.project_id.as_str())
            .push_static(", ")
            .bind(transition.committed_revision)
            .push_static(", ")
            .bind(transition.idempotency_key.as_str())
            .push_static(", ")
            .bind(transition.request_hash.as_str())
            .push_static(", ")
            .bind(transition.payload.to_string())
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(")")
            .build())
    }

    fn audit_insert(&self, audit: &WorkspaceContextAuditRecord) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_judge_audits (audit_id, tenant_id, project_id, \
                 workspace_id, plan_id, plan_node_id, user_id, judgment_type, agent_id, \
                 tool_name, input_json, output_json, rationale, latency_ms, status, error_detail, \
                 created_at) VALUES (",
            )
            .bind(audit.audit_id.as_str())
            .push_static(", ")
            .bind(audit.tenant_id.clone())
            .push_static(", ")
            .bind(audit.project_id.clone())
            .push_static(", NULL, NULL, NULL, ")
            .bind(audit.user_id.as_str())
            .push_static(", 'workspace_context_selection', ")
            .bind(audit.agent_id.as_str())
            .push_static(", ")
            .bind(audit.tool_name.as_str())
            .push_static(", ")
            .bind(audit.input.to_string())
            .push_static(", ")
            .bind(audit.output.to_string())
            .push_static(", ")
            .bind(audit.rationale.as_str())
            .push_static(", ")
            .bind(audit.latency_ms)
            .push_static(", ")
            .bind(audit.status.as_str())
            .push_static(", ")
            .bind(audit.error_detail.clone())
            .push_static(", ")
            .bind(audit.created_at.as_str())
            .push_static(")")
            .build()
    }

    fn outbox_insert(&self, transition: &WorkspaceContextTransition) -> DbStatement {
        DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_context_outbox (outbox_id, user_id, tenant_id, project_id, \
                 event_type, stream_name, event_sequence, payload_json, metadata_json, \
                 actor_api_key_id, idempotency_key, created_at, updated_at) VALUES (",
            )
            .bind(transition.outbox_id.as_str())
            .push_static(", ")
            .bind(transition.user_id.as_str())
            .push_static(", ")
            .bind(transition.selected.tenant_id.as_str())
            .push_static(", ")
            .bind(transition.selected.project_id.as_str())
            .push_static(", ")
            .bind(transition.event_type.as_str())
            .push_static(", ")
            .bind(format!("workspace-context:{}", transition.user_id))
            .push_static(", ")
            .bind(transition.committed_revision)
            .push_static(", ")
            .bind(transition.payload.to_string())
            .push_static(", ")
            .bind(transition.metadata.to_string())
            .push_static(", ")
            .bind(transition.actor_api_key_id.clone())
            .push_static(", ")
            .bind(transition.idempotency_key.as_str())
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(", ")
            .bind(transition.persisted_at.as_str())
            .push_static(")")
            .build()
    }
}

fn classify_transaction_error(
    error: DbError,
    membership_step: usize,
    context_step: usize,
) -> WorkspaceContextStoreError {
    if error.is_duplicate_key() {
        return WorkspaceContextStoreError::TransitionConflict;
    }
    if let DbError::TransactionExpectation { step_index, .. } = error {
        if step_index == membership_step {
            return WorkspaceContextStoreError::MembershipUnavailable;
        }
        if step_index == context_step {
            return WorkspaceContextStoreError::RevisionChanged;
        }
        return WorkspaceContextStoreError::TransitionConflict;
    }
    WorkspaceContextStoreError::Database(error)
}

fn access_from_row(
    row: &DbRow,
) -> Result<WorkspaceContextAccessSnapshot, WorkspaceContextStoreError> {
    Ok(WorkspaceContextAccessSnapshot {
        context: context_from_row(row)?,
        membership_role: required_string(row, "membership_role")?,
    })
}

fn context_from_row(row: &DbRow) -> Result<WorkspaceContextSnapshot, WorkspaceContextStoreError> {
    Ok(WorkspaceContextSnapshot {
        user_id: required_string(row, "user_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        revision: required_revision(row, "revision")?,
        updated_at: required_string(row, "updated_at")?,
    })
}

fn candidate_from_row(
    row: &DbRow,
) -> Result<WorkspaceContextCandidateSnapshot, WorkspaceContextStoreError> {
    Ok(WorkspaceContextCandidateSnapshot {
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        membership_role: required_string(row, "membership_role")?,
    })
}

fn event_from_row(row: &DbRow) -> Result<WorkspaceContextEventReceipt, WorkspaceContextStoreError> {
    Ok(WorkspaceContextEventReceipt {
        tenant_id: required_string(row, "to_tenant_id")?,
        project_id: required_string(row, "to_project_id")?,
        revision: required_revision(row, "revision")?,
        request_hash: required_string(row, "request_hash")?,
        created_at: required_string(row, "created_at")?,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceContextStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceContextStoreError::InvalidField(column))
}

fn required_revision(row: &DbRow, column: &'static str) -> Result<u64, WorkspaceContextStoreError> {
    let value = row
        .get_i64(column)?
        .ok_or(WorkspaceContextStoreError::InvalidField(column))?;
    u64::try_from(value).map_err(|_| WorkspaceContextStoreError::NegativeRevision)
}
