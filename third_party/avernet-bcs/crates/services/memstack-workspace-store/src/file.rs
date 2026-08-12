//! PostgreSQL/SQLite persistence for Workspace blackboard files.

use std::ops::Range;

use bcs_db_api::{
    DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder,
    DbTransactionStep, DbTransactionStepResult, DbValue,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use thiserror::Error;

/// Tenant/project/workspace scope for a file operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceFileScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Queryable metadata for one external object or directory.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceFileRecord {
    pub file_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub parent_path: String,
    pub name: String,
    pub is_directory: bool,
    pub file_size: u64,
    pub content_type: String,
    pub storage_backend: String,
    pub object_handle: String,
    pub object_state: String,
    pub uploader_type: String,
    pub uploader_id: String,
    pub uploader_actor_id: String,
    pub uploader_name: String,
    pub checksum_sha256: Option<String>,
    pub detected_mime_type: Option<String>,
    pub revision: u64,
    pub created_at: String,
    pub updated_at: String,
}

/// Durable upload lifecycle record used to resume after process failure.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceFileOperationRecord {
    pub operation_id: String,
    pub file_id: String,
    pub actor_id: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub state: String,
    pub staged_handle: Option<Value>,
    pub ready_handle: Option<Value>,
    pub checksum_sha256: Option<String>,
    pub size_bytes: Option<u64>,
}

/// Checked file writes applied in one authority transaction.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceFileDomainWrite {
    Insert(WorkspaceFileRecord),
    Update(WorkspaceFileRecord),
    Delete {
        file_id: String,
        descendant_path: Option<String>,
    },
    RenameMove {
        record: WorkspaceFileRecord,
        old_descendant_path: Option<String>,
        new_descendant_path: Option<String>,
    },
    InsertMany(Vec<WorkspaceFileRecord>),
    ActivateUpload {
        record: WorkspaceFileRecord,
        operation_id: String,
    },
}

/// Complete file mutation transaction input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceFileMutation {
    pub scope: WorkspaceFileScope,
    pub actor_id: String,
    pub action: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub expected_revision: u64,
    pub aggregate_id: String,
    pub domain_write: WorkspaceFileDomainWrite,
    pub response: Value,
    pub event_type: String,
    pub event_payload: Value,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or idempotently replayed file mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceFileMutationOutcome {
    pub receipt_id: String,
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable file persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceFileStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace membership required")]
    AccessRequired,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Workspace file not found")]
    FileNotFound,
    #[error("Workspace file mutation conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace file receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace file is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error("persisted Workspace file JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// Repository for scoped file reads, upload reservations, and atomic mutations.
pub struct WorkspaceFileStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceFileStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    pub async fn require_access(
        &self,
        scope: &WorkspaceFileScope,
        user_id: &str,
        require_editor: bool,
    ) -> Result<(), WorkspaceFileStoreError> {
        let rows = self
            .db
            .query(access_check(self.flavor, scope, user_id))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceFileStoreError::NotFound);
        };
        let role = required_string(row, "role")?;
        if require_editor && !matches!(role.as_str(), "owner" | "editor" | "admin") {
            return Err(WorkspaceFileStoreError::EditorAccessRequired);
        }
        Ok(())
    }

    pub async fn revision(
        &self,
        scope: &WorkspaceFileScope,
    ) -> Result<u64, WorkspaceFileStoreError> {
        let rows = self
            .db
            .query(revision_select(self.flavor, scope, None))
            .await?;
        let row = rows
            .first()
            .ok_or(WorkspaceFileStoreError::InvalidRecord("revision"))?;
        required_u64(row, "revision")
    }

    pub async fn list(
        &self,
        scope: &WorkspaceFileScope,
        parent_path: &str,
    ) -> Result<Vec<WorkspaceFileRecord>, WorkspaceFileStoreError> {
        self.db
            .query(file_select(
                self.flavor,
                scope,
                None,
                Some(parent_path),
                false,
            ))
            .await?
            .iter()
            .map(file_from_row)
            .collect()
    }

    pub async fn get(
        &self,
        scope: &WorkspaceFileScope,
        file_id: &str,
        include_staging: bool,
    ) -> Result<Option<WorkspaceFileRecord>, WorkspaceFileStoreError> {
        let rows = self
            .db
            .query(file_select(
                self.flavor,
                scope,
                Some(file_id),
                None,
                include_staging,
            ))
            .await?;
        rows.first().map(file_from_row).transpose()
    }

    pub async fn descendants(
        &self,
        scope: &WorkspaceFileScope,
        parent_prefix: &str,
    ) -> Result<Vec<WorkspaceFileRecord>, WorkspaceFileStoreError> {
        let pattern = format!("{parent_prefix}%");
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(FILE_COLUMNS)
            .push_static(" FROM workspace_files WHERE tenant_id = ")
            .bind(scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND object_state = 'ready' AND parent_path LIKE ")
            .bind(pattern)
            .push_static(" ORDER BY LENGTH(parent_path), parent_path, name")
            .build();
        self.db
            .query(statement)
            .await?
            .iter()
            .map(file_from_row)
            .collect()
    }

    pub async fn operation(
        &self,
        scope: &WorkspaceFileScope,
        actor_id: &str,
        idempotency_key: &str,
    ) -> Result<Option<WorkspaceFileOperationRecord>, WorkspaceFileStoreError> {
        let rows = self
            .db
            .query(operation_select(
                self.flavor,
                scope,
                actor_id,
                idempotency_key,
            ))
            .await?;
        rows.first().map(operation_from_row).transpose()
    }

    pub async fn replay(
        &self,
        mutation: &WorkspaceFileMutation,
    ) -> Result<Option<WorkspaceFileMutationOutcome>, WorkspaceFileStoreError> {
        self.read_receipt(mutation, true).await
    }

    /// Reserve staged object metadata without making the file visible.
    pub async fn reserve_upload(
        &self,
        operation: &WorkspaceFileOperationRecord,
        scope: &WorkspaceFileScope,
        record: &WorkspaceFileRecord,
    ) -> Result<WorkspaceFileOperationRecord, WorkspaceFileStoreError> {
        let results = self
            .db
            .transaction(vec![
                DbTransactionStep::query_checked(
                    access_check(self.flavor, scope, operation.actor_id.as_str()),
                    DbCountExpectation::exactly(1),
                ),
                DbTransactionStep::execute_checked(
                    operation_insert(self.flavor, scope, operation),
                    DbCountExpectation::exactly(1),
                ),
                DbTransactionStep::execute_checked(
                    file_insert(self.flavor, record),
                    DbCountExpectation::exactly(1),
                ),
                DbTransactionStep::query_checked(
                    operation_select(
                        self.flavor,
                        scope,
                        operation.actor_id.as_str(),
                        operation.idempotency_key.as_str(),
                    ),
                    DbCountExpectation::exactly(1),
                ),
            ])
            .await;
        match results {
            Ok(results) => operation_from_results(&results, 3),
            Err(error) if error.is_duplicate_key() => {
                let existing = self
                    .operation(
                        scope,
                        operation.actor_id.as_str(),
                        operation.idempotency_key.as_str(),
                    )
                    .await?
                    .ok_or(WorkspaceFileStoreError::Conflict)?;
                if existing.request_hash != operation.request_hash {
                    return Err(WorkspaceFileStoreError::IdempotencyConflict);
                }
                Ok(existing)
            }
            Err(error) => Err(error.into()),
        }
    }

    pub async fn mark_finalized(
        &self,
        scope: &WorkspaceFileScope,
        operation_id: &str,
        ready_handle: &Value,
    ) -> Result<(), WorkspaceFileStoreError> {
        self.db
            .execute(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "UPDATE workspace_file_operations SET state = 'finalized', ready_handle_json = ",
                    )
                    .bind(ready_handle.to_string())
                    .push_static(", last_error = NULL, updated_at = ")
                    .push_static(self.flavor.now())
                    .push_static(" WHERE tenant_id = ")
                    .bind(scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(scope.workspace_id.as_str())
                    .push_static(" AND operation_id = ")
                    .bind(operation_id)
                    .push_static(" AND state IN ('staged', 'finalized')")
                    .build(),
            )
            .await?;
        Ok(())
    }

    pub async fn record_compensation(
        &self,
        scope: &WorkspaceFileScope,
        operation_id: &str,
        file_id: &str,
        kind: &str,
        handle: &Value,
        error: &str,
    ) -> Result<(), WorkspaceFileStoreError> {
        let compensation_id = deterministic_id("file-compensation", operation_id, kind);
        let builder = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_file_compensations (compensation_id, operation_id, tenant_id, project_id, workspace_id, file_id, compensation_kind, object_handle_json, last_error) VALUES (",
            )
            .bind(compensation_id)
            .push_static(", ")
            .bind(operation_id)
            .push_static(", ")
            .bind(scope.tenant_id.as_str())
            .push_static(", ")
            .bind(scope.project_id.as_str())
            .push_static(", ")
            .bind(scope.workspace_id.as_str())
            .push_static(", ")
            .bind(file_id)
            .push_static(", ")
            .bind(kind)
            .push_static(", ")
            .bind(handle.to_string())
            .push_static(", ")
            .bind(error)
            .push_static(")");
        let statement = match self.flavor {
            DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
                .push_static(" ON CONFLICT(operation_id, compensation_kind) DO UPDATE SET last_error = excluded.last_error, next_attempt_at = CURRENT_TIMESTAMP, status = 'pending', updated_at = CURRENT_TIMESTAMP")
                .build(),
            DbSqlFlavor::Mysql => builder.build(),
        };
        self.db.execute(statement).await?;
        Ok(())
    }

    pub async fn mutate(
        &self,
        mutation: &WorkspaceFileMutation,
    ) -> Result<WorkspaceFileMutationOutcome, WorkspaceFileStoreError> {
        if let Some(outcome) = self.read_receipt(mutation, true).await? {
            return Ok(outcome);
        }
        let (steps, domain_range) = mutation_steps(self.flavor, mutation)?;
        let results = match self.db.transaction(steps).await {
            Ok(results) => results,
            Err(error) => {
                if error.is_duplicate_key()
                    && let Some(outcome) = self.read_receipt(mutation, true).await?
                {
                    return Ok(outcome);
                }
                return Err(classify_mutation_error(error, domain_range));
            }
        };
        let rows = transaction_rows(&results, results.len() - 1)?;
        let row = rows
            .first()
            .ok_or(WorkspaceFileStoreError::InvalidRecord("committed receipt"))?;
        receipt_outcome(mutation, row, false)?
            .ok_or(WorkspaceFileStoreError::InvalidRecord("committed receipt"))
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceFileMutation,
        replayed: bool,
    ) -> Result<Option<WorkspaceFileMutationOutcome>, WorkspaceFileStoreError> {
        let rows = self.db.query(receipt_lookup(self.flavor, mutation)).await?;
        rows.first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

const FILE_COLUMNS: &str = "SELECT file_id, tenant_id, project_id, workspace_id, parent_path, name, is_directory, file_size, content_type, storage_backend, object_handle, object_state, uploader_type, uploader_id, uploader_actor_id, uploader_name, checksum_sha256, detected_mime_type, revision, created_at, updated_at";

fn access_check(flavor: DbSqlFlavor, scope: &WorkspaceFileScope, user_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT m.role FROM workspace_profiles p JOIN workspace_members m ON m.tenant_id = p.tenant_id AND m.project_id = p.project_id AND m.workspace_id = p.workspace_id WHERE p.tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND p.project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND p.workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND p.deleted_at IS NULL AND m.user_id = ")
        .bind(user_id)
        .build()
}

fn file_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceFileScope,
    file_id: Option<&str>,
    parent_path: Option<&str>,
    include_staging: bool,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(FILE_COLUMNS)
        .push_static(" FROM workspace_files WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if !include_staging {
        builder = builder.push_static(" AND object_state = 'ready'");
    }
    if let Some(file_id) = file_id {
        builder = builder.push_static(" AND file_id = ").bind(file_id);
    }
    if let Some(parent_path) = parent_path {
        builder = builder
            .push_static(" AND parent_path = ")
            .bind(parent_path)
            .push_static(" ORDER BY is_directory DESC, name");
    }
    builder.build()
}

fn operation_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceFileScope,
    actor_id: &str,
    idempotency_key: &str,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT operation_id, file_id, actor_id, idempotency_key, request_hash, state, staged_handle_json, ready_handle_json, checksum_sha256, size_bytes FROM workspace_file_operations WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND actor_id = ")
        .bind(actor_id)
        .push_static(" AND idempotency_key = ")
        .bind(idempotency_key)
        .build()
}

fn operation_insert(
    flavor: DbSqlFlavor,
    scope: &WorkspaceFileScope,
    operation: &WorkspaceFileOperationRecord,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_file_operations (operation_id, tenant_id, project_id, workspace_id, file_id, actor_id, action, idempotency_key, request_hash, state, staged_handle_json, checksum_sha256, size_bytes) VALUES (")
        .bind(operation.operation_id.as_str())
        .push_static(", ").bind(scope.tenant_id.as_str())
        .push_static(", ").bind(scope.project_id.as_str())
        .push_static(", ").bind(scope.workspace_id.as_str())
        .push_static(", ").bind(operation.file_id.as_str())
        .push_static(", ").bind(operation.actor_id.as_str())
        .push_static(", 'upload_file', ").bind(operation.idempotency_key.as_str())
        .push_static(", ").bind(operation.request_hash.as_str())
        .push_static(", 'staged', ").bind(operation.staged_handle.as_ref().map(Value::to_string))
        .push_static(", ").bind(operation.checksum_sha256.clone())
        .push_static(", ")
        .bind(operation.size_bytes.map_or(DbValue::Null, DbValue::U64))
        .push_static(")")
        .build()
}

fn mutation_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceFileMutation,
) -> Result<(Vec<DbTransactionStep>, Range<usize>), WorkspaceFileStoreError> {
    let committed_revision = mutation
        .expected_revision
        .checked_add(1)
        .ok_or(WorkspaceFileStoreError::Conflict)?;
    let receipt_id = deterministic_id(
        "file-receipt",
        mutation.idempotency_key.as_str(),
        mutation.aggregate_id.as_str(),
    );
    let outbox_id = deterministic_id(
        "file-outbox",
        mutation.idempotency_key.as_str(),
        mutation.aggregate_id.as_str(),
    );
    let domain = domain_steps(flavor, mutation);
    let start = 3;
    let end = start + domain.len();
    let mut steps = vec![
        DbTransactionStep::query_checked(
            access_check(flavor, &mutation.scope, mutation.actor_id.as_str()),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::execute_checked(
            receipt_insert(flavor, mutation, receipt_id.as_str()),
            DbCountExpectation::exactly(1),
        ),
        DbTransactionStep::query_checked(
            revision_select(flavor, &mutation.scope, Some(mutation.expected_revision)),
            DbCountExpectation::exactly(1),
        ),
    ];
    steps.extend(domain.into_iter().map(|(statement, expectation)| {
        DbTransactionStep::execute_checked(statement, expectation)
    }));
    steps.extend([
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
    ]);
    Ok((steps, start..end))
}

fn domain_steps(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceFileMutation,
) -> Vec<(DbStatement, DbCountExpectation)> {
    match &mutation.domain_write {
        WorkspaceFileDomainWrite::Insert(record) => {
            vec![(file_insert(flavor, record), DbCountExpectation::exactly(1))]
        }
        WorkspaceFileDomainWrite::Update(record) => {
            vec![(file_update(flavor, record), DbCountExpectation::exactly(1))]
        }
        WorkspaceFileDomainWrite::Delete {
            file_id,
            descendant_path,
        } => {
            let mut statements = Vec::new();
            if let Some(prefix) = descendant_path {
                statements.push((
                    descendant_delete(flavor, &mutation.scope, prefix),
                    DbCountExpectation::at_least(0),
                ));
            }
            statements.push((
                file_delete(flavor, &mutation.scope, file_id),
                DbCountExpectation::exactly(1),
            ));
            statements
        }
        WorkspaceFileDomainWrite::RenameMove {
            record,
            old_descendant_path,
            new_descendant_path,
        } => {
            let mut statements = Vec::new();
            if let (Some(old), Some(new)) = (old_descendant_path, new_descendant_path) {
                statements.push((
                    descendant_move(flavor, &mutation.scope, old, new),
                    DbCountExpectation::at_least(0),
                ));
            }
            statements.push((file_update(flavor, record), DbCountExpectation::exactly(1)));
            statements
        }
        WorkspaceFileDomainWrite::InsertMany(records) => records
            .iter()
            .map(|record| (file_insert(flavor, record), DbCountExpectation::exactly(1)))
            .collect(),
        WorkspaceFileDomainWrite::ActivateUpload {
            record,
            operation_id,
        } => vec![
            (file_update(flavor, record), DbCountExpectation::exactly(1)),
            (
                DbStatementBuilder::new(flavor)
                    .push_static(
                        "UPDATE workspace_file_operations SET state = 'completed', completed_at = ",
                    )
                    .push_static(flavor.now())
                    .push_static(", updated_at = ")
                    .push_static(flavor.now())
                    .push_static(" WHERE tenant_id = ")
                    .bind(mutation.scope.tenant_id.as_str())
                    .push_static(" AND project_id = ")
                    .bind(mutation.scope.project_id.as_str())
                    .push_static(" AND workspace_id = ")
                    .bind(mutation.scope.workspace_id.as_str())
                    .push_static(" AND operation_id = ")
                    .bind(operation_id.as_str())
                    .push_static(" AND state IN ('finalized', 'completed')")
                    .build(),
                DbCountExpectation::exactly(1),
            ),
        ],
    }
}

fn file_insert(flavor: DbSqlFlavor, file: &WorkspaceFileRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_files (file_id, tenant_id, project_id, workspace_id, parent_path, name, is_directory, file_size, content_type, storage_backend, object_handle, object_state, uploader_type, uploader_id, uploader_actor_id, uploader_name, checksum_sha256, detected_mime_type, revision, created_at, updated_at) VALUES (")
        .bind(file.file_id.as_str()).push_static(", ").bind(file.tenant_id.as_str())
        .push_static(", ").bind(file.project_id.as_str()).push_static(", ").bind(file.workspace_id.as_str())
        .push_static(", ").bind(file.parent_path.as_str()).push_static(", ").bind(file.name.as_str())
        .push_static(", ").bind(file.is_directory).push_static(", ").bind(file.file_size)
        .push_static(", ").bind(file.content_type.as_str()).push_static(", ").bind(file.storage_backend.as_str())
        .push_static(", ").bind(file.object_handle.as_str()).push_static(", ").bind(file.object_state.as_str())
        .push_static(", ").bind(file.uploader_type.as_str()).push_static(", ").bind(file.uploader_id.as_str())
        .push_static(", ").bind(file.uploader_actor_id.as_str()).push_static(", ").bind(file.uploader_name.as_str())
        .push_static(", ").bind(file.checksum_sha256.clone()).push_static(", ").bind(file.detected_mime_type.clone())
        .push_static(", ").bind(file.revision).push_static(", ").bind(file.created_at.as_str())
        .push_static(", ").bind(file.updated_at.as_str()).push_static(")").build()
}

fn file_update(flavor: DbSqlFlavor, file: &WorkspaceFileRecord) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_files SET parent_path = ")
        .bind(file.parent_path.as_str())
        .push_static(", name = ")
        .bind(file.name.as_str())
        .push_static(", file_size = ")
        .bind(file.file_size)
        .push_static(", content_type = ")
        .bind(file.content_type.as_str())
        .push_static(", storage_backend = ")
        .bind(file.storage_backend.as_str())
        .push_static(", object_handle = ")
        .bind(file.object_handle.as_str())
        .push_static(", object_state = ")
        .bind(file.object_state.as_str())
        .push_static(", checksum_sha256 = ")
        .bind(file.checksum_sha256.clone())
        .push_static(", detected_mime_type = ")
        .bind(file.detected_mime_type.clone())
        .push_static(", revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(file.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(file.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(file.workspace_id.as_str())
        .push_static(" AND file_id = ")
        .bind(file.file_id.as_str())
        .push_static(" AND revision = ")
        .bind(file.revision)
        .build()
}

fn descendant_move(
    flavor: DbSqlFlavor,
    scope: &WorkspaceFileScope,
    old: &str,
    new: &str,
) -> DbStatement {
    let pattern = format!("{old}%");
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_files SET parent_path = ")
        .bind(new)
        .push_static(" || SUBSTR(parent_path, ")
        .bind(old.chars().count().saturating_add(1) as u64)
        .push_static("), revision = revision + 1, updated_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND parent_path LIKE ")
        .bind(pattern)
        .build()
}

fn descendant_delete(flavor: DbSqlFlavor, scope: &WorkspaceFileScope, prefix: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("DELETE FROM workspace_files WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND parent_path LIKE ")
        .bind(format!("{prefix}%"))
        .build()
}

fn file_delete(flavor: DbSqlFlavor, scope: &WorkspaceFileScope, file_id: &str) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("DELETE FROM workspace_files WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND file_id = ")
        .bind(file_id)
        .build()
}

fn revision_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceFileScope,
    expected: Option<u64>,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static("SELECT revision FROM workspace_authorities WHERE tenant_id = ")
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(expected) = expected {
        builder = builder.push_static(" AND revision = ").bind(expected);
    }
    if flavor == DbSqlFlavor::Postgres {
        builder.push_static(" FOR UPDATE").build()
    } else {
        builder.build()
    }
}

fn receipt_insert(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceFileMutation,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "blackboard_file", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
    let builder = DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_mutation_receipts (receipt_id, tenant_id, project_id, workspace_id, actor_id, contract_version, surface, action, idempotency_key, request_hash, expected_revision) VALUES (")
        .bind(receipt_id).push_static(", ").bind(mutation.scope.tenant_id.as_str())
        .push_static(", ").bind(mutation.scope.project_id.as_str()).push_static(", ").bind(mutation.scope.workspace_id.as_str())
        .push_static(", ").bind(mutation.actor_id.as_str()).push_static(", ").bind(contract_version)
        .push_static(", ").bind(surface).push_static(", ").bind(action)
        .push_static(", ").bind(mutation.idempotency_key.as_str())
        .push_static(", ").bind(mutation.request_hash.as_str()).push_static(", ").bind(mutation.expected_revision)
        .push_static(")");
    match flavor {
        DbSqlFlavor::Postgres | DbSqlFlavor::Sqlite => builder
            .push_static(" ON CONFLICT(workspace_id, actor_id, idempotency_key) DO NOTHING")
            .build(),
        DbSqlFlavor::Mysql => builder.build(),
    }
}

fn receipt_lookup(flavor: DbSqlFlavor, mutation: &WorkspaceFileMutation) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("SELECT request_hash, committed_revision, response_json FROM workspace_mutation_receipts WHERE tenant_id = ").bind(mutation.scope.tenant_id.as_str())
        .push_static(" AND project_id = ").bind(mutation.scope.project_id.as_str())
        .push_static(" AND workspace_id = ").bind(mutation.scope.workspace_id.as_str())
        .push_static(" AND actor_id = ").bind(mutation.actor_id.as_str())
        .push_static(" AND idempotency_key = ").bind(mutation.idempotency_key.as_str()).build()
}

fn authority_cas(flavor: DbSqlFlavor, mutation: &WorkspaceFileMutation) -> DbStatement {
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
    mutation: &WorkspaceFileMutation,
    outbox_id: &str,
    revision: u64,
    receipt_id: &str,
) -> DbStatement {
    let (contract_version, surface, action) = mutation.receipt_authority.as_ref().map_or(
        ("v1", "blackboard", mutation.action.as_str()),
        |authority| {
            (
                authority.contract_version().as_str(),
                authority.surface().as_str(),
                authority.action().as_str(),
            )
        },
    );
    let metadata = json!({"action": action, "authority_class": "authoritative", "contract_version": contract_version, "receipt_id": receipt_id, "request_hash": mutation.request_hash, "signal_role": "sensing-capable", "surface_boundary": "owned", "surface_owner": surface});
    DbStatementBuilder::new(flavor)
        .push_static("INSERT INTO workspace_outbox (outbox_id, tenant_id, project_id, workspace_id, aggregate_type, aggregate_id, event_type, stream_name, event_sequence, payload_json, metadata_json, correlation_id, idempotency_key) VALUES (")
        .bind(outbox_id).push_static(", ").bind(mutation.scope.tenant_id.as_str())
        .push_static(", ").bind(mutation.scope.project_id.as_str()).push_static(", ").bind(mutation.scope.workspace_id.as_str())
        .push_static(", 'blackboard_file', ").bind(mutation.aggregate_id.as_str())
        .push_static(", ").bind(mutation.event_type.as_str()).push_static(", ").bind(format!("workspace:events:{}", mutation.scope.workspace_id))
        .push_static(", ").bind(revision).push_static(", ").bind(mutation.event_payload.to_string())
        .push_static(", ").bind(metadata.to_string()).push_static(", ").bind(receipt_id)
        .push_static(", ").bind(mutation.idempotency_key.as_str()).push_static(")").build()
}

fn receipt_finalize(
    flavor: DbSqlFlavor,
    mutation: &WorkspaceFileMutation,
    receipt_id: &str,
    revision: u64,
) -> DbStatement {
    DbStatementBuilder::new(flavor)
        .push_static("UPDATE workspace_mutation_receipts SET committed_revision = ")
        .bind(revision)
        .push_static(", response_json = ")
        .bind(mutation.response.to_string())
        .push_static(", committed_at = ")
        .push_static(flavor.now())
        .push_static(" WHERE receipt_id = ")
        .bind(receipt_id)
        .push_static(" AND committed_revision IS NULL")
        .build()
}

fn receipt_outcome(
    mutation: &WorkspaceFileMutation,
    row: &DbRow,
    replayed: bool,
) -> Result<Option<WorkspaceFileMutationOutcome>, WorkspaceFileStoreError> {
    let request_hash = required_string(row, "request_hash")?;
    if request_hash != mutation.request_hash {
        return Err(WorkspaceFileStoreError::IdempotencyConflict);
    }
    let Some(revision) = optional_u64(row, "committed_revision")? else {
        return Ok(None);
    };
    let response = required_json(row, "response_json")?;
    Ok(Some(WorkspaceFileMutationOutcome {
        receipt_id: deterministic_id(
            "file-receipt",
            mutation.idempotency_key.as_str(),
            mutation.aggregate_id.as_str(),
        ),
        committed_revision: revision,
        response,
        outbox_id: deterministic_id(
            "file-outbox",
            mutation.idempotency_key.as_str(),
            mutation.aggregate_id.as_str(),
        ),
        replayed,
    }))
}

fn classify_mutation_error(error: DbError, domain: Range<usize>) -> WorkspaceFileStoreError {
    match &error {
        DbError::TransactionExpectation { step_index: 0, .. } => {
            WorkspaceFileStoreError::EditorAccessRequired
        }
        DbError::TransactionExpectation { step_index: 2, .. } => WorkspaceFileStoreError::Conflict,
        DbError::TransactionExpectation { step_index, .. } if domain.contains(step_index) => {
            WorkspaceFileStoreError::Conflict
        }
        _ if error.is_duplicate_key() => WorkspaceFileStoreError::Conflict,
        _ => WorkspaceFileStoreError::Database(error),
    }
}

fn file_from_row(row: &DbRow) -> Result<WorkspaceFileRecord, WorkspaceFileStoreError> {
    Ok(WorkspaceFileRecord {
        file_id: required_string(row, "file_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        parent_path: required_string(row, "parent_path")?,
        name: required_string(row, "name")?,
        is_directory: row
            .get_bool("is_directory")?
            .ok_or(WorkspaceFileStoreError::InvalidRecord("is_directory"))?,
        file_size: required_u64(row, "file_size")?,
        content_type: required_string(row, "content_type")?,
        storage_backend: required_string(row, "storage_backend")?,
        object_handle: required_string(row, "object_handle")?,
        object_state: required_string(row, "object_state")?,
        uploader_type: required_string(row, "uploader_type")?,
        uploader_id: required_string(row, "uploader_id")?,
        uploader_actor_id: required_string(row, "uploader_actor_id")?,
        uploader_name: required_string(row, "uploader_name")?,
        checksum_sha256: optional_string(row, "checksum_sha256")?,
        detected_mime_type: optional_string(row, "detected_mime_type")?,
        revision: required_u64(row, "revision")?,
        created_at: required_string(row, "created_at")?,
        updated_at: required_string(row, "updated_at")?,
    })
}

fn operation_from_row(
    row: &DbRow,
) -> Result<WorkspaceFileOperationRecord, WorkspaceFileStoreError> {
    Ok(WorkspaceFileOperationRecord {
        operation_id: required_string(row, "operation_id")?,
        file_id: required_string(row, "file_id")?,
        actor_id: required_string(row, "actor_id")?,
        idempotency_key: required_string(row, "idempotency_key")?,
        request_hash: required_string(row, "request_hash")?,
        state: required_string(row, "state")?,
        staged_handle: optional_json(row, "staged_handle_json")?,
        ready_handle: optional_json(row, "ready_handle_json")?,
        checksum_sha256: optional_string(row, "checksum_sha256")?,
        size_bytes: optional_u64(row, "size_bytes")?,
    })
}

fn operation_from_results(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<WorkspaceFileOperationRecord, WorkspaceFileStoreError> {
    let rows = transaction_rows(results, index)?;
    rows.first()
        .ok_or(WorkspaceFileStoreError::InvalidRecord("operation"))
        .and_then(operation_from_row)
}

fn transaction_rows(
    results: &[DbTransactionStepResult],
    index: usize,
) -> Result<&[DbRow], WorkspaceFileStoreError> {
    match results.get(index) {
        Some(DbTransactionStepResult::Rows(rows)) => Ok(rows),
        _ => Err(WorkspaceFileStoreError::InvalidRecord("transaction rows")),
    }
}

fn required_string(row: &DbRow, field: &'static str) -> Result<String, WorkspaceFileStoreError> {
    row.get_string(field)?
        .ok_or(WorkspaceFileStoreError::InvalidRecord(field))
}
fn optional_string(
    row: &DbRow,
    field: &'static str,
) -> Result<Option<String>, WorkspaceFileStoreError> {
    Ok(row.get_string(field)?)
}
fn required_u64(row: &DbRow, field: &'static str) -> Result<u64, WorkspaceFileStoreError> {
    optional_u64(row, field)?.ok_or(WorkspaceFileStoreError::InvalidRecord(field))
}
fn optional_u64(row: &DbRow, field: &'static str) -> Result<Option<u64>, WorkspaceFileStoreError> {
    row.get_i64(field)?
        .map(|value| {
            u64::try_from(value).map_err(|_| WorkspaceFileStoreError::InvalidRecord(field))
        })
        .transpose()
}
fn required_json(row: &DbRow, field: &'static str) -> Result<Value, WorkspaceFileStoreError> {
    optional_json(row, field)?.ok_or(WorkspaceFileStoreError::InvalidRecord(field))
}
fn optional_json(
    row: &DbRow,
    field: &'static str,
) -> Result<Option<Value>, WorkspaceFileStoreError> {
    row.get_string(field)?
        .map(|value| serde_json::from_str(&value).map_err(WorkspaceFileStoreError::InvalidJson))
        .transpose()
}
fn deterministic_id(namespace: &str, first: &str, second: &str) -> String {
    let digest = Sha256::digest(format!("{namespace}\0{first}\0{second}"));
    format!("{namespace}-{}", hex::encode(&digest[..16]))
}
