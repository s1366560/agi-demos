//! PostgreSQL/SQLite persistence for the Workspace Objective authority.

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::Value;
use sha2::{Digest, Sha256};
use thiserror::Error;

use crate::WorkspaceObjectiveTaskProjection;

/// Tenant/project/workspace scope for one Objective operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceObjectiveScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical Objective fields required by the legacy HTTP contract.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceObjectiveRecord {
    pub objective_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub objective_type: String,
    pub parent_objective_id: Option<String>,
    pub progress: f64,
    pub created_by_actor_id: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Checked Objective domain write.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceObjectiveDomainWrite {
    Create(WorkspaceObjectiveRecord),
    Update(WorkspaceObjectiveRecord),
    Delete { objective_id: String },
}

/// Complete Objective mutation transaction input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceObjectiveMutation {
    pub scope: WorkspaceObjectiveScope,
    pub actor_id: String,
    pub actor_is_superuser: bool,
    pub action: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub expected_revision: u64,
    pub objective_id: String,
    pub domain_write: WorkspaceObjectiveDomainWrite,
    pub response: Value,
    pub event_type: String,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or replayed Objective mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceObjectiveMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable Objective persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceObjectiveStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace membership required")]
    AccessRequired,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Objective not found")]
    ObjectiveNotFound,
    #[error("Workspace Objective mutation conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace Objective receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace Objective is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite Objective repository.
pub struct WorkspaceObjectiveStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceObjectiveStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require scoped membership and optionally editor authority.
    pub async fn require_access(
        &self,
        scope: &WorkspaceObjectiveScope,
        user_id: &str,
        require_editor: bool,
        is_superuser: bool,
    ) -> Result<(), WorkspaceObjectiveStoreError> {
        if self
            .db
            .query(workspace_exists(self.flavor, scope))
            .await?
            .is_empty()
        {
            return Err(WorkspaceObjectiveStoreError::NotFound);
        }
        if is_superuser {
            return Ok(());
        }
        let rows = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceObjectiveStoreError::AccessRequired);
        };
        if require_editor
            && !matches!(
                required_string(row, "role")?.as_str(),
                "owner" | "editor" | "admin"
            )
        {
            return Err(WorkspaceObjectiveStoreError::EditorAccessRequired);
        }
        Ok(())
    }

    /// Read the current Workspace revision.
    pub async fn revision(
        &self,
        scope: &WorkspaceObjectiveScope,
    ) -> Result<u64, WorkspaceObjectiveStoreError> {
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
        let revision = required_i64(
            rows.first()
                .ok_or(WorkspaceObjectiveStoreError::InvalidRecord("revision"))?,
            "revision",
        )?;
        u64::try_from(revision).map_err(|_| WorkspaceObjectiveStoreError::InvalidRecord("revision"))
    }

    /// Read one scoped Objective.
    pub async fn get(
        &self,
        scope: &WorkspaceObjectiveScope,
        objective_id: &str,
    ) -> Result<Option<WorkspaceObjectiveRecord>, WorkspaceObjectiveStoreError> {
        self.db
            .query(objective_select(
                self.flavor,
                scope,
                Some(objective_id),
                None,
                None,
                1,
                0,
            ))
            .await?
            .first()
            .map(objective_from_row)
            .transpose()
    }

    /// List scoped Objectives in legacy creation order.
    pub async fn list(
        &self,
        scope: &WorkspaceObjectiveScope,
        objective_type: Option<&str>,
        parent_objective_id: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceObjectiveRecord>, WorkspaceObjectiveStoreError> {
        self.db
            .query(objective_select(
                self.flavor,
                scope,
                None,
                objective_type,
                parent_objective_id,
                limit,
                offset,
            ))
            .await?
            .iter()
            .map(objective_from_row)
            .collect()
    }

    /// Resolve the formal Task projection for one Objective.
    pub async fn projected_task(
        &self,
        scope: &WorkspaceObjectiveScope,
        objective_id: &str,
    ) -> Result<Option<WorkspaceObjectiveTaskProjection>, WorkspaceObjectiveStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT task_id, committed_revision, outbox_id \
                         FROM workspace_objective_task_projections \
                         WHERE tenant_id = ",
                    )
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .push_static(" AND objective_id = ")
                    .bind(objective_id)
                    .build(),
            )
            .await?;
        rows.first()
            .map(|row| {
                Ok(WorkspaceObjectiveTaskProjection {
                    task_id: required_string(row, "task_id")?,
                    committed_revision: u64::try_from(required_i64(row, "committed_revision")?)
                        .map_err(|_| {
                            WorkspaceObjectiveStoreError::InvalidRecord("committed_revision")
                        })?,
                    outbox_id: required_string(row, "outbox_id")?,
                })
            })
            .transpose()
    }

    /// Execute one atomic Objective mutation or replay its receipt.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceObjectiveMutation,
    ) -> Result<WorkspaceObjectiveMutationOutcome, WorkspaceObjectiveStoreError> {
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
                return Err(classify_mutation_error(error, mutation));
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceObjectiveStoreError::IncompleteReceipt);
        };
        receipt_outcome(
            mutation,
            rows.first()
                .ok_or(WorkspaceObjectiveStoreError::IncompleteReceipt)?,
            false,
        )?
        .ok_or(WorkspaceObjectiveStoreError::IncompleteReceipt)
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceObjectiveMutation,
        statement: DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceObjectiveMutationOutcome>, WorkspaceObjectiveStoreError> {
        self.db
            .query(statement)
            .await?
            .first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceObjectiveMutation,
) -> Result<Vec<DbTransactionStep>, WorkspaceObjectiveStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceObjectiveStoreError::Conflict)?;
    let receipt_id = deterministic_id("objective-receipt", mutation);
    let outbox_id = deterministic_id("objective-outbox", mutation);
    Ok(vec![
        DbTransactionStep::query_checked(
            editor_access_check(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_insert(flavor, mutation, receipt_id.as_str()),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            revision_check(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            domain_statement(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            authority_cas(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            outbox_insert(flavor, mutation, outbox_id.as_str(), committed_revision),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_finalize(flavor, mutation, receipt_id.as_str(), committed_revision),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            receipt_lookup(flavor, mutation),
            DbCountExpectation::exactly(1),
        ),
    ])
}

fn classify_mutation_error(
    error: DbError,
    mutation: &WorkspaceObjectiveMutation,
) -> WorkspaceObjectiveStoreError {
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        return match *step_index {
            0 => WorkspaceObjectiveStoreError::EditorAccessRequired,
            1 | 2 => WorkspaceObjectiveStoreError::Conflict,
            3 if matches!(
                mutation.domain_write,
                WorkspaceObjectiveDomainWrite::Delete { .. }
            ) =>
            {
                WorkspaceObjectiveStoreError::ObjectiveNotFound
            }
            3..=6 => WorkspaceObjectiveStoreError::Conflict,
            _ => WorkspaceObjectiveStoreError::Database(error),
        };
    }
    if error.is_duplicate_key() {
        WorkspaceObjectiveStoreError::Conflict
    } else {
        WorkspaceObjectiveStoreError::Database(error)
    }
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceObjectiveScope) -> DbStatement {
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

fn member_role(flavor: DbSqlFlavor, scope: &WorkspaceObjectiveScope, user_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT role FROM workspace_members WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND user_id = ")
        .bind(user_id)
        .build()
}

#[allow(clippy::too_many_arguments)]
fn objective_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceObjectiveScope,
    objective_id: Option<&str>,
    objective_type: Option<&str>,
    parent_objective_id: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT objective_id, tenant_id, project_id, workspace_id, title, description, \
             objective_type, parent_objective_id, CAST(progress AS TEXT) AS progress, \
             created_by_actor_id, created_at, \
             updated_at FROM workspace_objectives WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(objective_id) = objective_id {
        builder = builder
            .push_static(" AND objective_id = ")
            .bind(objective_id);
    }
    if let Some(objective_type) = objective_type {
        builder = builder
            .push_static(" AND objective_type = ")
            .bind(objective_type);
    }
    if let Some(parent_objective_id) = parent_objective_id {
        builder = builder
            .push_static(" AND parent_objective_id = ")
            .bind(parent_objective_id);
    }
    builder
        .push_static(" ORDER BY created_at ASC, objective_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn editor_access_check(flavor: DbSqlFlavor, mutation: &WorkspaceObjectiveMutation) -> DbStatement {
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

fn receipt_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceObjectiveMutation,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "objective", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
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
        .push_static(", ")
        .bind(contract_version)
        .push_static(", ")
        .bind(surface)
        .push_static(", ")
        .bind(action)
        .push_static(", ")
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

fn receipt_lookup(flavor: DbSqlFlavor, mutation: &WorkspaceObjectiveMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT request_hash, committed_revision, response_json FROM \
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

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceObjectiveMutation) -> DbStatement {
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

fn domain_statement(flavor: DbSqlFlavor, mutation: &WorkspaceObjectiveMutation) -> DbStatement {
    match &mutation.domain_write {
        WorkspaceObjectiveDomainWrite::Create(record) => insert_objective(flavor, record),
        WorkspaceObjectiveDomainWrite::Update(record) => update_objective(flavor, record),
        WorkspaceObjectiveDomainWrite::Delete { objective_id } => DbStatementBuilder::new(flavor)
            .push_static("DELETE FROM workspace_objectives WHERE tenant_id = ")
            .bind(mutation.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(mutation.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(mutation.scope.workspace_id.as_str())
            .push_static(" AND objective_id = ")
            .bind(objective_id.as_str())
            .build(),
    }
}

fn insert_objective(flavor: DbSqlFlavor, record: &WorkspaceObjectiveRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_objectives (objective_id, tenant_id, project_id, workspace_id, \
             title, description, objective_type, parent_objective_id, progress, \
             created_by_actor_id, created_at, updated_at) VALUES (",
        )
        .bind(record.objective_id.as_str())
        .push_static(", ")
        .bind(record.tenant_id.as_str())
        .push_static(", ")
        .bind(record.project_id.as_str())
        .push_static(", ")
        .bind(record.workspace_id.as_str())
        .push_static(", ")
        .bind(record.title.as_str())
        .push_static(", ")
        .bind(record.description.clone())
        .push_static(", ")
        .bind(record.objective_type.as_str())
        .push_static(", ")
        .bind(record.parent_objective_id.clone())
        .push_static(", ")
        .bind(record.progress)
        .push_static(", ")
        .bind(record.created_by_actor_id.as_str())
        .push_static(", ")
        .bind(record.created_at.as_str())
        .push_static(", ")
        .bind(record.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_objective(flavor: DbSqlFlavor, record: &WorkspaceObjectiveRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_objectives SET title = ")
        .bind(record.title.as_str())
        .push_static(", description = ")
        .bind(record.description.clone())
        .push_static(", objective_type = ")
        .bind(record.objective_type.as_str())
        .push_static(", parent_objective_id = ")
        .bind(record.parent_objective_id.clone())
        .push_static(", progress = ")
        .bind(record.progress)
        .push_static(", updated_at = ")
        .bind(record.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(record.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(record.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(record.workspace_id.as_str())
        .push_static(" AND objective_id = ")
        .bind(record.objective_id.as_str())
        .build()
}

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceObjectiveMutation) -> DbStatement {
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
    mutation: &WorkspaceObjectiveMutation,
    outbox_id: &str,
    committed_revision: u64,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "objectives", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
    let payload = serde_json::json!({
        "objective_id": &mutation.objective_id,
        "workspace_id": &mutation.scope.workspace_id,
        "response": &mutation.response,
    });
    let metadata = serde_json::json!({
        "action": action,
        "contract_version": contract_version,
        "request_hash": &mutation.request_hash,
        "surface": surface,
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
        .push_static(", 'workspace_objective', ")
        .bind(mutation.objective_id.as_str())
        .push_static(", ")
        .bind(mutation.event_type.as_str())
        .push_static(", ")
        .bind(format!("workspace:{}", mutation.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(payload.to_string())
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
    mutation: &WorkspaceObjectiveMutation,
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
    mutation: &WorkspaceObjectiveMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceObjectiveMutationOutcome>, WorkspaceObjectiveStoreError> {
    if required_string(row, "request_hash")? != mutation.request_hash {
        return Err(WorkspaceObjectiveStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Ok(None);
    };
    let response_raw = required_string(row, "response_json")?;
    let response = serde_json::from_str(&response_raw)
        .map_err(|_| WorkspaceObjectiveStoreError::InvalidRecord("response_json"))?;
    Ok(Some(WorkspaceObjectiveMutationOutcome {
        committed_revision: u64::try_from(committed_revision)
            .map_err(|_| WorkspaceObjectiveStoreError::InvalidRecord("committed_revision"))?,
        response,
        outbox_id: deterministic_id("objective-outbox", mutation),
        replayed,
    }))
}

fn objective_from_row(
    row: &DbRow,
) -> Result<WorkspaceObjectiveRecord, WorkspaceObjectiveStoreError> {
    Ok(WorkspaceObjectiveRecord {
        objective_id: required_string(row, "objective_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        title: required_string(row, "title")?,
        description: row.get_string("description")?,
        objective_type: required_string(row, "objective_type")?,
        parent_objective_id: row.get_string("parent_objective_id")?,
        progress: required_string(row, "progress")?
            .parse::<f64>()
            .map_err(|_| WorkspaceObjectiveStoreError::InvalidRecord("progress"))?,
        created_by_actor_id: required_string(row, "created_by_actor_id")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceObjectiveStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceObjectiveStoreError::InvalidRecord(column))
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceObjectiveStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceObjectiveStoreError::InvalidRecord(column))
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceObjectiveMutation) -> String {
    let mut digest = Sha256::new();
    let (surface, action) = mutation
        .receipt_authority
        .as_ref()
        .map_or(("objectives", mutation.action.as_str()), |authority| {
            (authority.surface().as_str(), authority.action().as_str())
        });
    for part in [
        namespace,
        mutation.scope.tenant_id.as_str(),
        mutation.scope.project_id.as_str(),
        mutation.scope.workspace_id.as_str(),
        mutation.actor_id.as_str(),
        surface,
        action,
        mutation.idempotency_key.as_str(),
        mutation.request_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}
