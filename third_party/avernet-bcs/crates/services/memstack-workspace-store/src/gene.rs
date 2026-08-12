//! PostgreSQL/SQLite persistence for the Workspace Gene authority.

use std::ops::Range;

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Tenant/project/workspace scope for one Gene operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceGeneScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical persisted Gene record. `version` is an internal monotonic
/// revision; the legacy HTTP contract exposes `source_version`.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceGeneRecord {
    pub gene_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub name: String,
    pub description: Option<String>,
    pub category: String,
    pub status: String,
    pub version: i64,
    pub source_version: String,
    pub is_active: bool,
    pub config_text: Option<String>,
    pub content: Value,
    pub content_hash: String,
    pub created_by_actor_id: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Checked Gene write applied with the Workspace authority transaction.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceGeneDomainWrite {
    Create(WorkspaceGeneRecord),
    Update(WorkspaceGeneRecord),
    Delete { gene_id: String },
}

/// Complete Gene mutation transaction input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceGeneMutation {
    pub scope: WorkspaceGeneScope,
    pub actor_id: String,
    pub actor_is_superuser: bool,
    pub action: String,
    pub idempotency_key: String,
    pub payload_hash: String,
    pub expected_revision: u64,
    pub aggregate_id: String,
    pub domain_write: WorkspaceGeneDomainWrite,
    pub response: Value,
    pub event_type: String,
    pub event_payload: Value,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or idempotently replayed Gene mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceGeneMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable Gene persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceGeneStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace membership required")]
    AccessRequired,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Gene not found")]
    GeneNotFound,
    #[error("Workspace Gene mutation conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace Gene receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace Gene is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error("persisted Workspace Gene JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite repository for Gene reads and atomic writes.
pub struct WorkspaceGeneStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceGeneStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require scoped membership and optionally editor authority.
    pub async fn require_access(
        &self,
        scope: &WorkspaceGeneScope,
        user_id: &str,
        require_editor: bool,
        is_superuser: bool,
    ) -> Result<(), WorkspaceGeneStoreError> {
        if self
            .db
            .query(workspace_exists(self.flavor, scope))
            .await?
            .is_empty()
        {
            return Err(WorkspaceGeneStoreError::NotFound);
        }
        if is_superuser {
            return Ok(());
        }
        let rows = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceGeneStoreError::AccessRequired);
        };
        if require_editor
            && !matches!(
                required_string(row, "role")?.as_str(),
                "owner" | "editor" | "admin"
            )
        {
            return Err(WorkspaceGeneStoreError::EditorAccessRequired);
        }
        Ok(())
    }

    /// Read the current Workspace authority revision.
    pub async fn revision(
        &self,
        scope: &WorkspaceGeneScope,
    ) -> Result<u64, WorkspaceGeneStoreError> {
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
                .ok_or(WorkspaceGeneStoreError::InvalidRecord("revision"))?,
            "revision",
        )?;
        u64::try_from(revision).map_err(|_| WorkspaceGeneStoreError::InvalidRecord("revision"))
    }

    /// Read one scoped Gene.
    pub async fn get(
        &self,
        scope: &WorkspaceGeneScope,
        gene_id: &str,
    ) -> Result<Option<WorkspaceGeneRecord>, WorkspaceGeneStoreError> {
        self.db
            .query(gene_select(
                self.flavor,
                scope,
                Some(gene_id),
                None,
                None,
                1,
                0,
            ))
            .await?
            .first()
            .map(gene_from_row)
            .transpose()
    }

    /// List scoped Genes in legacy creation order.
    pub async fn list(
        &self,
        scope: &WorkspaceGeneScope,
        category: Option<&str>,
        is_active: Option<bool>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceGeneRecord>, WorkspaceGeneStoreError> {
        self.db
            .query(gene_select(
                self.flavor,
                scope,
                None,
                category,
                is_active,
                limit,
                offset,
            ))
            .await?
            .iter()
            .map(gene_from_row)
            .collect()
    }

    /// Execute one atomic Gene mutation or replay its committed receipt.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceGeneMutation,
    ) -> Result<WorkspaceGeneMutationOutcome, WorkspaceGeneStoreError> {
        let lookup = receipt_lookup(self.flavor, mutation);
        if let Some(outcome) = self.read_receipt(mutation, lookup.clone(), true).await? {
            return Ok(outcome);
        }
        let (steps, domain_range) = mutation_steps(self.flavor, mutation)?;
        let results = match self.db.transaction(steps).await {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_receipt(mutation, lookup, true).await?
                {
                    return Ok(outcome);
                }
                return Err(classify_mutation_error(error, domain_range, mutation));
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceGeneStoreError::InvalidRecord("receipt result"));
        };
        receipt_outcome(
            mutation,
            rows.first()
                .ok_or(WorkspaceGeneStoreError::InvalidRecord("receipt"))?,
            false,
        )?
        .ok_or(WorkspaceGeneStoreError::InvalidRecord("committed receipt"))
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceGeneMutation,
        statement: DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceGeneMutationOutcome>, WorkspaceGeneStoreError> {
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
    mutation: &WorkspaceGeneMutation,
) -> Result<(Vec<DbTransactionStep>, Range<usize>), WorkspaceGeneStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceGeneStoreError::Conflict)?;
    let receipt_id = deterministic_id("gene-receipt", mutation);
    let outbox_id = deterministic_id("gene-outbox", mutation);
    let domain_range = 3..4;
    Ok((
        vec![
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
                outbox_insert(
                    flavor,
                    mutation,
                    outbox_id.as_str(),
                    committed_revision,
                    receipt_id.as_str(),
                ),
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
        ],
        domain_range,
    ))
}

fn classify_mutation_error(
    error: DbError,
    domain_range: Range<usize>,
    mutation: &WorkspaceGeneMutation,
) -> WorkspaceGeneStoreError {
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        return match *step_index {
            0 => WorkspaceGeneStoreError::EditorAccessRequired,
            1 | 2 => WorkspaceGeneStoreError::Conflict,
            index if domain_range.contains(&index) => match mutation.domain_write {
                WorkspaceGeneDomainWrite::Delete { .. } => WorkspaceGeneStoreError::GeneNotFound,
                _ => WorkspaceGeneStoreError::Conflict,
            },
            _ => WorkspaceGeneStoreError::Database(error),
        };
    }
    if error.is_duplicate_key() {
        WorkspaceGeneStoreError::Conflict
    } else {
        WorkspaceGeneStoreError::Database(error)
    }
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceGeneScope) -> DbStatement {
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

fn member_role(flavor: DbSqlFlavor, scope: &WorkspaceGeneScope, user_id: &str) -> DbStatement {
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

fn gene_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceGeneScope,
    gene_id: Option<&str>,
    category: Option<&str>,
    is_active: Option<bool>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT gene_id, tenant_id, project_id, workspace_id, name, description, category, \
             status, version, source_version, is_active, config_text, content_json, content_hash, \
             created_by_actor_id, created_at, updated_at FROM workspace_genes WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(gene_id) = gene_id {
        builder = builder.push_static(" AND gene_id = ").bind(gene_id);
    }
    if let Some(category) = category {
        builder = builder.push_static(" AND category = ").bind(category);
    }
    if let Some(is_active) = is_active {
        builder = builder.push_static(" AND is_active = ").bind(is_active);
    }
    builder
        .push_static(" ORDER BY created_at ASC, gene_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn editor_access_check(flavor: DbSqlFlavor, mutation: &WorkspaceGeneMutation) -> DbStatement {
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
    mutation: &WorkspaceGeneMutation,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "gene", mutation.action.as_str()),
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
        .bind(mutation.payload_hash.as_str())
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

fn receipt_lookup(flavor: DbSqlFlavor, mutation: &WorkspaceGeneMutation) -> DbStatement {
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

fn revision_check(flavor: DbSqlFlavor, mutation: &WorkspaceGeneMutation) -> DbStatement {
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

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceGeneMutation) -> DbStatement {
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

fn domain_statement(flavor: DbSqlFlavor, mutation: &WorkspaceGeneMutation) -> DbStatement {
    match &mutation.domain_write {
        WorkspaceGeneDomainWrite::Create(record) => insert_gene(flavor, record),
        WorkspaceGeneDomainWrite::Update(record) => update_gene(flavor, record),
        WorkspaceGeneDomainWrite::Delete { gene_id } => DbStatementBuilder::new(flavor)
            .push_static("DELETE FROM workspace_genes WHERE tenant_id = ")
            .bind(mutation.scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(mutation.scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(mutation.scope.workspace_id.as_str())
            .push_static(" AND gene_id = ")
            .bind(gene_id.as_str())
            .build(),
    }
}

fn insert_gene(flavor: DbSqlFlavor, record: &WorkspaceGeneRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static(
            "INSERT INTO workspace_genes (gene_id, tenant_id, project_id, workspace_id, name, \
             description, category, status, version, source_version, is_active, config_text, \
             content_json, content_hash, created_by_actor_id, metadata_json, created_at, updated_at) \
             VALUES (",
        )
        .bind(record.gene_id.as_str())
        .push_static(", ")
        .bind(record.tenant_id.as_str())
        .push_static(", ")
        .bind(record.project_id.as_str())
        .push_static(", ")
        .bind(record.workspace_id.as_str())
        .push_static(", ")
        .bind(record.name.as_str())
        .push_static(", ")
        .bind(record.description.clone())
        .push_static(", ")
        .bind(record.category.as_str())
        .push_static(", ")
        .bind(record.status.as_str())
        .push_static(", ")
        .bind(record.version)
        .push_static(", ")
        .bind(record.source_version.as_str())
        .push_static(", ")
        .bind(record.is_active)
        .push_static(", ")
        .bind(record.config_text.clone())
        .push_static(", ")
        .bind(record.content.to_string())
        .push_static(", ")
        .bind(record.content_hash.as_str())
        .push_static(", ")
        .bind(record.created_by_actor_id.as_str())
        .push_static(", '{}', ")
        .bind(record.created_at.as_str())
        .push_static(", ")
        .bind(record.updated_at.clone())
        .push_static(")")
        .build()
}

fn update_gene(flavor: DbSqlFlavor, record: &WorkspaceGeneRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_genes SET name = ")
        .bind(record.name.as_str())
        .push_static(", description = ")
        .bind(record.description.clone())
        .push_static(", category = ")
        .bind(record.category.as_str())
        .push_static(", status = ")
        .bind(record.status.as_str())
        .push_static(", version = ")
        .bind(record.version)
        .push_static(", source_version = ")
        .bind(record.source_version.as_str())
        .push_static(", is_active = ")
        .bind(record.is_active)
        .push_static(", config_text = ")
        .bind(record.config_text.clone())
        .push_static(", content_json = ")
        .bind(record.content.to_string())
        .push_static(", content_hash = ")
        .bind(record.content_hash.as_str())
        .push_static(", updated_at = ")
        .bind(record.updated_at.clone())
        .push_static(" WHERE tenant_id = ")
        .bind(record.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(record.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(record.workspace_id.as_str())
        .push_static(" AND gene_id = ")
        .bind(record.gene_id.as_str())
        .build()
}

fn outbox_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceGeneMutation,
    outbox_id: &str,
    committed_revision: u64,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, action) =
        mutation
            .receipt_authority
            .as_ref()
            .map_or(("v1", mutation.action.as_str()), |authority| {
                (
                    authority.contract_version().as_str(),
                    authority.action().as_str(),
                )
            });
    let metadata = json!({
        "action": action,
        "contract_version": contract_version,
        "receipt_id": receipt_id,
        "request_hash": &mutation.payload_hash,
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
        .push_static(", 'gene', ")
        .bind(mutation.aggregate_id.as_str())
        .push_static(", ")
        .bind(mutation.event_type.as_str())
        .push_static(", ")
        .bind(format!("workspace:{}", mutation.scope.workspace_id))
        .push_static(", ")
        .bind(committed_revision)
        .push_static(", ")
        .bind(mutation.event_payload.to_string())
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
    mutation: &WorkspaceGeneMutation,
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
        .bind(mutation.payload_hash.as_str())
        .push_static(" AND committed_revision IS NULL")
        .build()
}

fn receipt_outcome(
    mutation: &WorkspaceGeneMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceGeneMutationOutcome>, WorkspaceGeneStoreError> {
    if required_string(row, "request_hash")? != mutation.payload_hash {
        return Err(WorkspaceGeneStoreError::IdempotencyConflict);
    }
    let Some(committed_revision) = row.get_i64("committed_revision")? else {
        return Err(WorkspaceGeneStoreError::IncompleteReceipt);
    };
    let response = required_json_object(row, "response_json")?;
    Ok(Some(WorkspaceGeneMutationOutcome {
        committed_revision: u64::try_from(committed_revision)
            .map_err(|_| WorkspaceGeneStoreError::InvalidRecord("committed_revision"))?,
        response,
        outbox_id: deterministic_id("gene-outbox", mutation),
        replayed,
    }))
}

fn deterministic_id(namespace: &str, mutation: &WorkspaceGeneMutation) -> String {
    let mut digest = Sha256::new();
    let (surface, action) = mutation
        .receipt_authority
        .as_ref()
        .map_or(("gene", mutation.action.as_str()), |authority| {
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
        mutation.payload_hash.as_str(),
    ] {
        digest.update(u64::try_from(part.len()).unwrap_or(u64::MAX).to_be_bytes());
        digest.update(part.as_bytes());
    }
    format!("{namespace}-{}", hex::encode(digest.finalize()))
}

fn gene_from_row(row: &DbRow) -> Result<WorkspaceGeneRecord, WorkspaceGeneStoreError> {
    Ok(WorkspaceGeneRecord {
        gene_id: required_string(row, "gene_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        name: required_string(row, "name")?,
        description: row.get_string("description")?,
        category: required_string(row, "category")?,
        status: required_string(row, "status")?,
        version: required_i64(row, "version")?,
        source_version: required_string(row, "source_version")?,
        is_active: required_bool(row, "is_active")?,
        config_text: row.get_string("config_text")?,
        content: required_json_object(row, "content_json")?,
        content_hash: required_string(row, "content_hash")?,
        created_by_actor_id: required_string(row, "created_by_actor_id")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspaceGeneStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceGeneStoreError::InvalidRecord(column))
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceGeneStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceGeneStoreError::InvalidRecord(column))
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, WorkspaceGeneStoreError> {
    row.get_bool(column)?
        .ok_or(WorkspaceGeneStoreError::InvalidRecord(column))
}

fn required_json_object(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceGeneStoreError> {
    let encoded = required_string(row, column)?;
    let value: Value =
        serde_json::from_str(&encoded).map_err(WorkspaceGeneStoreError::InvalidJson)?;
    value
        .is_object()
        .then_some(value)
        .ok_or(WorkspaceGeneStoreError::InvalidRecord(column))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn scope() -> WorkspaceGeneScope {
        WorkspaceGeneScope {
            tenant_id: "tenant-1".to_string(),
            project_id: "project-1".to_string(),
            workspace_id: "workspace-1".to_string(),
        }
    }

    #[test]
    fn select_uses_dialect_placeholders_and_formal_filters() {
        let postgres = gene_select(
            DbSqlFlavor::Postgres,
            &scope(),
            None,
            Some("skill"),
            Some(true),
            100,
            0,
        );
        assert!(postgres.sql().contains("category = $4"));
        assert!(postgres.sql().contains("is_active = $5"));
        let sqlite = gene_select(DbSqlFlavor::Sqlite, &scope(), None, None, None, 100, 0);
        assert!(sqlite.sql().contains("tenant_id = ?"));
        assert!(!sqlite.sql().contains('$'));
    }
}
