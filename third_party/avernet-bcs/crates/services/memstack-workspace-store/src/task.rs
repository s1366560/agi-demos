//! Atomic persistence for the legacy-compatible Workspace Task authority.

use bcs_db_api::{
    DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStepResult,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::Value;
use thiserror::Error;

use crate::task_mutation::{mutation_steps, receipt_lookup, receipt_outcome};

/// Tenant/project/workspace scope for one Task operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical persisted Task projection.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskRecord {
    pub task_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub title: String,
    pub description: Option<String>,
    pub created_by: String,
    pub assignee_user_id: Option<String>,
    pub assignee_agent_id: Option<String>,
    pub status: String,
    pub priority: i64,
    pub estimated_effort: Option<String>,
    pub blocker_reason: Option<String>,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub completed_at: Option<String>,
    pub archived_at: Option<String>,
}

/// One persisted execution attempt used by Task execution read models.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskAttemptRecord {
    pub attempt_id: String,
    pub task_id: String,
    pub root_goal_task_id: String,
    pub attempt_number: i64,
    pub status: String,
    pub conversation_id: Option<String>,
    pub worker_agent_id: Option<String>,
    pub leader_agent_id: Option<String>,
    pub candidate_summary: Option<String>,
    pub candidate_artifacts: Value,
    pub candidate_verifications: Value,
    pub leader_feedback: Option<String>,
    pub adjudication_reason: Option<String>,
    pub created_at: String,
    pub updated_at: Option<String>,
    pub completed_at: Option<String>,
}

/// Latest runtime correlation and terminal facts for one Task.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskExecutionRecord {
    pub correlation_id: String,
    pub conversation_id: String,
    pub attempt_id: Option<String>,
    pub status: String,
    pub execution_status: Option<String>,
    pub updated_at: String,
    pub completed_at: Option<String>,
}

/// Formal relation written when one Objective is materialized as a root Task.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceObjectiveTaskProjectionWrite {
    pub projection_id: String,
    pub objective_id: String,
    pub task_id: String,
    pub actor_id: String,
    pub created_at: String,
}

/// Persisted Objective-to-Task materialization authority.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceObjectiveTaskProjection {
    pub task_id: String,
    pub committed_revision: u64,
    pub outbox_id: String,
}

/// Checked Task write prepared by the application service.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceTaskDomainWrite {
    Create(WorkspaceTaskRecord),
    Update(WorkspaceTaskRecord),
    Delete { task_id: String },
}

/// Additional checked write applied in the same Task transaction.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum WorkspaceTaskAuxiliaryWrite {
    CreateAttempt(WorkspaceTaskAttemptRecord),
    QueueDispatch(crate::WorkspaceTaskDispatchWrite),
    CreateObjectiveProjection(WorkspaceObjectiveTaskProjectionWrite),
}

/// Complete Task mutation transaction input.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskMutation {
    pub scope: WorkspaceTaskScope,
    pub actor_id: String,
    pub action: String,
    pub idempotency_key: String,
    pub payload_hash: String,
    pub expected_revision: u64,
    pub task_id: String,
    pub domain_write: WorkspaceTaskDomainWrite,
    pub auxiliary_writes: Vec<WorkspaceTaskAuxiliaryWrite>,
    pub response: Value,
    pub event_type: String,
    pub event_payload: Value,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or idempotently replayed Task mutation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceTaskMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable Task persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceTaskStoreError {
    #[error("Workspace not found")]
    NotFound,

    #[error("Workspace membership required")]
    AccessRequired,

    #[error("Workspace editor access required")]
    EditorAccessRequired,

    #[error("Workspace task not found")]
    TaskNotFound,

    #[error("Workspace task mutation conflicted with current authority")]
    Conflict,

    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,

    #[error("Workspace task receipt is incomplete")]
    IncompleteReceipt,

    #[error("Workspace task dispatch claim is invalid")]
    InvalidDispatchClaim,

    #[error("Workspace task dispatch lease was lost")]
    DispatchLeaseLost,

    #[error("Workspace task dispatch runtime correlation conflicts")]
    DispatchCorrelationConflict,

    #[error("persisted Workspace task is invalid: {0}")]
    InvalidRecord(&'static str),

    #[error("persisted Workspace task JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),

    #[error(transparent)]
    Database(#[from] DbError),
}

/// PostgreSQL/SQLite repository for the Workspace Task authority.
pub struct WorkspaceTaskStore<'a> {
    pub(crate) db: &'a dyn DbPlugin,
    pub(crate) flavor: DbSqlFlavor,
}

impl<'a> WorkspaceTaskStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require a scoped Workspace membership and optionally editor authority.
    ///
    /// # Errors
    ///
    /// Returns a stable not-found/access error or preserves a database failure.
    pub async fn require_access(
        &self,
        scope: &WorkspaceTaskScope,
        user_id: &str,
        require_editor: bool,
    ) -> Result<(), WorkspaceTaskStoreError> {
        let profile = self.db.query(workspace_exists(self.flavor, scope)).await?;
        if profile.is_empty() {
            return Err(WorkspaceTaskStoreError::NotFound);
        }
        let rows = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(row) = rows.first() else {
            return Err(WorkspaceTaskStoreError::AccessRequired);
        };
        if require_editor {
            let role = required_string(row, "role")?;
            if !matches!(role.as_str(), "owner" | "editor" | "admin") {
                return Err(WorkspaceTaskStoreError::EditorAccessRequired);
            }
        }
        Ok(())
    }

    /// Read one scoped Task after its caller has passed access checks.
    ///
    /// # Errors
    ///
    /// Returns a row-decoding or database error.
    pub async fn get(
        &self,
        scope: &WorkspaceTaskScope,
        task_id: &str,
    ) -> Result<Option<WorkspaceTaskRecord>, WorkspaceTaskStoreError> {
        let rows = self
            .db
            .query(task_select(self.flavor, scope, Some(task_id), None, 1, 0))
            .await?;
        rows.first().map(task_from_row).transpose()
    }

    /// List scoped Tasks newest-first with an optional exact status filter.
    ///
    /// # Errors
    ///
    /// Returns a row-decoding or database error.
    pub async fn list(
        &self,
        scope: &WorkspaceTaskScope,
        status: Option<&str>,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceTaskRecord>, WorkspaceTaskStoreError> {
        self.db
            .query(task_select(self.flavor, scope, None, status, limit, offset))
            .await?
            .iter()
            .map(task_from_row)
            .collect()
    }

    /// Resolve one binding without dropping its persisted scope.
    ///
    /// # Errors
    ///
    /// Returns a row-decoding or database error.
    pub async fn agent_binding(
        &self,
        binding_id: &str,
    ) -> Result<Option<(String, String, String, String, bool)>, WorkspaceTaskStoreError> {
        let rows = self
            .db
            .query(
                DbStatementBuilder::new(self.flavor)
                    .push_static(
                        "SELECT tenant_id, project_id, workspace_id, agent_id, is_active \
                         FROM workspace_agent_bindings WHERE binding_id = ",
                    )
                    .bind(binding_id)
                    .build(),
            )
            .await?;
        rows.first()
            .map(|row| {
                Ok((
                    required_string(row, "tenant_id")?,
                    required_string(row, "project_id")?,
                    required_string(row, "workspace_id")?,
                    required_string(row, "agent_id")?,
                    required_bool(row, "is_active")?,
                ))
            })
            .transpose()
    }

    /// Read the current scoped Workspace authority revision.
    ///
    /// # Errors
    ///
    /// Returns `NotFound` when no authority exists or preserves a database failure.
    pub async fn revision(
        &self,
        scope: &WorkspaceTaskScope,
    ) -> Result<u64, WorkspaceTaskStoreError> {
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
        let row = rows.first().ok_or(WorkspaceTaskStoreError::NotFound)?;
        u64::try_from(required_i64(row, "revision")?)
            .map_err(|_| WorkspaceTaskStoreError::InvalidRecord("revision"))
    }

    /// Read recent persisted attempts newest-first.
    ///
    /// # Errors
    ///
    /// Returns a row-decoding or database error.
    pub async fn attempts(
        &self,
        scope: &WorkspaceTaskScope,
        task_id: &str,
        limit: i64,
    ) -> Result<Vec<WorkspaceTaskAttemptRecord>, WorkspaceTaskStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT attempt_id, task_id, root_goal_task_id, attempt_number, status, \
                 conversation_id, worker_agent_id, leader_agent_id, candidate_summary, \
                 candidate_artifacts_json, candidate_verifications_json, leader_feedback, \
                 adjudication_reason, created_at, updated_at, completed_at \
                 FROM workspace_task_attempts WHERE tenant_id = ",
            )
            .bind(scope.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND task_id = ")
            .bind(task_id)
            .push_static(" ORDER BY attempt_number DESC, attempt_id ASC LIMIT ")
            .bind(limit)
            .build();
        self.db
            .query(statement)
            .await?
            .iter()
            .map(attempt_from_row)
            .collect()
    }

    /// Read the latest structural runtime/terminal facts for one Task.
    ///
    /// # Errors
    ///
    /// Returns a row-decoding or database error.
    pub async fn execution(
        &self,
        scope: &WorkspaceTaskScope,
        task_id: &str,
    ) -> Result<Option<WorkspaceTaskExecutionRecord>, WorkspaceTaskStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT c.correlation_id, c.conversation_id, c.attempt_id, c.status, \
                 t.execution_status, c.updated_at, c.completed_at \
                 FROM workspace_agent_runtime_correlations c \
                 LEFT JOIN workspace_execution_terminals t \
                   ON t.correlation_id = c.correlation_id \
                 WHERE c.tenant_id = ",
            )
            .bind(scope.tenant_id.as_str())
            .push_static(" AND c.project_id = ")
            .bind(scope.project_id.as_str())
            .push_static(" AND c.workspace_id = ")
            .bind(scope.workspace_id.as_str())
            .push_static(" AND c.task_id = ")
            .bind(task_id)
            .push_static(" ORDER BY c.updated_at DESC, c.correlation_id ASC LIMIT 1")
            .build();
        let rows = self.db.query(statement).await?;
        rows.first().map(execution_from_row).transpose()
    }

    /// Execute one Task mutation with membership, receipt, revision CAS, and outbox atomically.
    ///
    /// # Errors
    ///
    /// Returns stable access, idempotency, authority-conflict, decoding, or database errors.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceTaskMutation,
    ) -> Result<WorkspaceTaskMutationOutcome, WorkspaceTaskStoreError> {
        self.require_access(&mutation.scope, mutation.actor_id.as_str(), true)
            .await?;
        if let Some(outcome) = self.read_replay(mutation, true).await? {
            return Ok(outcome);
        }
        let steps = mutation_steps(self.flavor, mutation)?;
        let results = match self.db.transaction(steps).await {
            Ok(results) => results,
            Err(error) => {
                if let Some(outcome) = self.read_replay(mutation, true).await? {
                    return Ok(outcome);
                }
                if matches!(error, DbError::TransactionExpectation { .. })
                    || error.is_duplicate_key()
                {
                    return Err(WorkspaceTaskStoreError::Conflict);
                }
                return Err(error.into());
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceTaskStoreError::IncompleteReceipt);
        };
        let Some(row) = rows.first() else {
            return Err(WorkspaceTaskStoreError::IncompleteReceipt);
        };
        receipt_outcome(mutation, row, false)?.ok_or(WorkspaceTaskStoreError::IncompleteReceipt)
    }

    async fn read_replay(
        &self,
        mutation: &WorkspaceTaskMutation,
        replayed: bool,
    ) -> Result<Option<WorkspaceTaskMutationOutcome>, WorkspaceTaskStoreError> {
        let rows = self.db.query(receipt_lookup(self.flavor, mutation)).await?;
        rows.first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceTaskScope) -> DbStatement {
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

fn member_role(flavor: DbSqlFlavor, scope: &WorkspaceTaskScope, user_id: &str) -> DbStatement {
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

fn task_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceTaskScope,
    task_id: Option<&str>,
    status: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT task_id, tenant_id, project_id, workspace_id, title, description, \
             created_by, assignee_user_id, assignee_agent_id, status, priority, \
             estimated_effort, blocker_reason, metadata_json, created_at, updated_at, \
             completed_at, archived_at FROM workspace_tasks WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(task_id) = task_id {
        builder = builder.push_static(" AND task_id = ").bind(task_id);
    }
    if let Some(status) = status {
        builder = builder.push_static(" AND status = ").bind(status);
    }
    builder
        .push_static(" ORDER BY created_at DESC, task_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn task_from_row(row: &DbRow) -> Result<WorkspaceTaskRecord, WorkspaceTaskStoreError> {
    Ok(WorkspaceTaskRecord {
        task_id: required_string(row, "task_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        title: required_string(row, "title")?,
        description: optional_string(row, "description")?,
        created_by: required_string(row, "created_by")?,
        assignee_user_id: optional_string(row, "assignee_user_id")?,
        assignee_agent_id: optional_string(row, "assignee_agent_id")?,
        status: required_string(row, "status")?,
        priority: required_i64(row, "priority")?,
        estimated_effort: optional_string(row, "estimated_effort")?,
        blocker_reason: optional_string(row, "blocker_reason")?,
        metadata: required_json_object(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
        completed_at: optional_string(row, "completed_at")?,
        archived_at: optional_string(row, "archived_at")?,
    })
}

fn attempt_from_row(row: &DbRow) -> Result<WorkspaceTaskAttemptRecord, WorkspaceTaskStoreError> {
    Ok(WorkspaceTaskAttemptRecord {
        attempt_id: required_string(row, "attempt_id")?,
        task_id: required_string(row, "task_id")?,
        root_goal_task_id: required_string(row, "root_goal_task_id")?,
        attempt_number: required_i64(row, "attempt_number")?,
        status: required_string(row, "status")?,
        conversation_id: optional_string(row, "conversation_id")?,
        worker_agent_id: optional_string(row, "worker_agent_id")?,
        leader_agent_id: optional_string(row, "leader_agent_id")?,
        candidate_summary: optional_string(row, "candidate_summary")?,
        candidate_artifacts: required_json_array(row, "candidate_artifacts_json")?,
        candidate_verifications: required_json_array(row, "candidate_verifications_json")?,
        leader_feedback: optional_string(row, "leader_feedback")?,
        adjudication_reason: optional_string(row, "adjudication_reason")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
        completed_at: optional_string(row, "completed_at")?,
    })
}

fn execution_from_row(
    row: &DbRow,
) -> Result<WorkspaceTaskExecutionRecord, WorkspaceTaskStoreError> {
    Ok(WorkspaceTaskExecutionRecord {
        correlation_id: required_string(row, "correlation_id")?,
        conversation_id: required_string(row, "conversation_id")?,
        attempt_id: optional_string(row, "attempt_id")?,
        status: required_string(row, "status")?,
        execution_status: optional_string(row, "execution_status")?,
        updated_at: required_string(row, "updated_at")?,
        completed_at: optional_string(row, "completed_at")?,
    })
}

pub(super) fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceTaskStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspaceTaskStoreError> {
    row.get_string(column).map_err(Into::into)
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspaceTaskStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(column))
}

fn required_bool(row: &DbRow, column: &'static str) -> Result<bool, WorkspaceTaskStoreError> {
    row.get_bool(column)?
        .ok_or(WorkspaceTaskStoreError::InvalidRecord(column))
}

pub(super) fn required_json_object(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceTaskStoreError> {
    let value: Value = serde_json::from_str(&required_string(row, column)?)
        .map_err(WorkspaceTaskStoreError::InvalidJson)?;
    if value.is_object() {
        Ok(value)
    } else {
        Err(WorkspaceTaskStoreError::InvalidRecord(column))
    }
}

fn required_json_array(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceTaskStoreError> {
    let value: Value = serde_json::from_str(&required_string(row, column)?)
        .map_err(WorkspaceTaskStoreError::InvalidJson)?;
    if value.is_array() {
        Ok(value)
    } else {
        Err(WorkspaceTaskStoreError::InvalidRecord(column))
    }
}
