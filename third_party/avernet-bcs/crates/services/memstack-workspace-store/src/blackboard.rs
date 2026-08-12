//! PostgreSQL/SQLite persistence for Workspace blackboard posts and replies.

use bcs_db_api::{
    DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatement, DbStatementBuilder, DbTransactionStepResult,
};
use memstack_workspace_service_api::WorkspaceMutationAuthority;
use serde_json::Value;
use thiserror::Error;

use crate::blackboard_mutation::{mutation_steps, receipt_lookup, receipt_outcome};

/// Tenant/project/workspace scope for one blackboard operation.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspaceBlackboardScope {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
}

/// Canonical blackboard post projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceBlackboardPostRecord {
    pub post_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub author_actor_id: String,
    pub title: String,
    pub content: String,
    pub status: String,
    pub is_pinned: bool,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Canonical blackboard reply projection.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceBlackboardReplyRecord {
    pub reply_id: String,
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub post_id: String,
    pub author_actor_id: String,
    pub content: String,
    pub metadata: Value,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// Checked blackboard write applied inside one authority transaction.
#[derive(Debug, Clone, PartialEq)]
pub enum WorkspaceBlackboardDomainWrite {
    CreatePost(WorkspaceBlackboardPostRecord),
    UpdatePost(WorkspaceBlackboardPostRecord),
    DeletePost { post_id: String },
    CreateReply(WorkspaceBlackboardReplyRecord),
    UpdateReply(WorkspaceBlackboardReplyRecord),
    DeleteReply { post_id: String, reply_id: String },
}

/// Complete blackboard mutation transaction input.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceBlackboardMutation {
    pub scope: WorkspaceBlackboardScope,
    pub actor_id: String,
    pub action: String,
    pub idempotency_key: String,
    pub payload_hash: String,
    pub expected_revision: u64,
    pub aggregate_id: String,
    pub domain_write: WorkspaceBlackboardDomainWrite,
    pub response: Value,
    pub event_type: String,
    pub event_payload: Value,
    pub receipt_authority: Option<WorkspaceMutationAuthority>,
}

/// Committed or idempotently replayed blackboard mutation.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspaceBlackboardMutationOutcome {
    pub committed_revision: u64,
    pub response: Value,
    pub outbox_id: String,
    pub replayed: bool,
}

/// Stable blackboard persistence failures.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspaceBlackboardStoreError {
    #[error("Workspace not found")]
    NotFound,
    #[error("Workspace membership required")]
    AccessRequired,
    #[error("Workspace editor access required")]
    EditorAccessRequired,
    #[error("Blackboard post not found")]
    PostNotFound,
    #[error("Blackboard reply not found")]
    ReplyNotFound,
    #[error("Workspace blackboard mutation conflicted with current authority")]
    Conflict,
    #[error("idempotency key was already used with a different request hash")]
    IdempotencyConflict,
    #[error("Workspace blackboard receipt is incomplete")]
    IncompleteReceipt,
    #[error("persisted Workspace blackboard is invalid: {0}")]
    InvalidRecord(&'static str),
    #[error("persisted Workspace blackboard JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),
    #[error(transparent)]
    Database(#[from] DbError),
}

/// Repository for scoped reads and atomic blackboard mutations.
pub struct WorkspaceBlackboardStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspaceBlackboardStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Require scoped membership and optionally editor authority.
    pub async fn require_access(
        &self,
        scope: &WorkspaceBlackboardScope,
        user_id: &str,
        require_editor: bool,
    ) -> Result<(), WorkspaceBlackboardStoreError> {
        let profiles = self.db.query(workspace_exists(self.flavor, scope)).await?;
        if profiles.is_empty() {
            return Err(WorkspaceBlackboardStoreError::NotFound);
        }
        let roles = self
            .db
            .query(member_role(self.flavor, scope, user_id))
            .await?;
        let Some(role) = roles.first() else {
            return Err(WorkspaceBlackboardStoreError::AccessRequired);
        };
        if require_editor {
            let role = required_string(role, "role")?;
            if !matches!(role.as_str(), "owner" | "editor" | "admin") {
                return Err(WorkspaceBlackboardStoreError::EditorAccessRequired);
            }
        }
        Ok(())
    }

    /// Read the current Workspace authority revision.
    pub async fn revision(
        &self,
        scope: &WorkspaceBlackboardScope,
    ) -> Result<u64, WorkspaceBlackboardStoreError> {
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
        let row = rows
            .first()
            .ok_or(WorkspaceBlackboardStoreError::InvalidRecord("revision"))?;
        let revision = row
            .get_i64("revision")?
            .ok_or(WorkspaceBlackboardStoreError::InvalidRecord("revision"))?;
        u64::try_from(revision)
            .map_err(|_| WorkspaceBlackboardStoreError::InvalidRecord("revision"))
    }

    /// Read one scoped post after access has been checked.
    pub async fn get_post(
        &self,
        scope: &WorkspaceBlackboardScope,
        post_id: &str,
    ) -> Result<Option<WorkspaceBlackboardPostRecord>, WorkspaceBlackboardStoreError> {
        let rows = self
            .db
            .query(post_select(self.flavor, scope, Some(post_id), 1, 0))
            .await?;
        rows.first().map(post_from_row).transpose()
    }

    /// List posts in legacy pinned-first, newest-first order.
    pub async fn list_posts(
        &self,
        scope: &WorkspaceBlackboardScope,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceBlackboardPostRecord>, WorkspaceBlackboardStoreError> {
        self.db
            .query(post_select(self.flavor, scope, None, limit, offset))
            .await?
            .iter()
            .map(post_from_row)
            .collect()
    }

    /// Read one reply scoped to both Workspace and parent post.
    pub async fn get_reply(
        &self,
        scope: &WorkspaceBlackboardScope,
        post_id: &str,
        reply_id: &str,
    ) -> Result<Option<WorkspaceBlackboardReplyRecord>, WorkspaceBlackboardStoreError> {
        let rows = self
            .db
            .query(reply_select(
                self.flavor,
                scope,
                post_id,
                Some(reply_id),
                1,
                0,
            ))
            .await?;
        rows.first().map(reply_from_row).transpose()
    }

    /// List replies in legacy creation order.
    pub async fn list_replies(
        &self,
        scope: &WorkspaceBlackboardScope,
        post_id: &str,
        limit: i64,
        offset: i64,
    ) -> Result<Vec<WorkspaceBlackboardReplyRecord>, WorkspaceBlackboardStoreError> {
        self.db
            .query(reply_select(
                self.flavor,
                scope,
                post_id,
                None,
                limit,
                offset,
            ))
            .await?
            .iter()
            .map(reply_from_row)
            .collect()
    }

    /// Execute one atomic blackboard mutation or replay its committed receipt.
    pub async fn mutate(
        &self,
        mutation: &WorkspaceBlackboardMutation,
    ) -> Result<WorkspaceBlackboardMutationOutcome, WorkspaceBlackboardStoreError> {
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
                return Err(classify_mutation_error(error, domain_range));
            }
        };
        let Some(DbTransactionStepResult::Rows(rows)) = results.last() else {
            return Err(WorkspaceBlackboardStoreError::InvalidRecord(
                "receipt result",
            ));
        };
        let row = rows
            .first()
            .ok_or(WorkspaceBlackboardStoreError::InvalidRecord("receipt"))?;
        receipt_outcome(mutation, row, false)?.ok_or(WorkspaceBlackboardStoreError::InvalidRecord(
            "committed receipt",
        ))
    }

    async fn read_receipt(
        &self,
        mutation: &WorkspaceBlackboardMutation,
        statement: DbStatement,
        replayed: bool,
    ) -> Result<Option<WorkspaceBlackboardMutationOutcome>, WorkspaceBlackboardStoreError> {
        let rows = self.db.query(statement).await?;
        rows.first()
            .map(|row| receipt_outcome(mutation, row, replayed))
            .transpose()
            .map(Option::flatten)
    }
}

fn classify_mutation_error(
    error: DbError,
    domain_range: std::ops::Range<usize>,
) -> WorkspaceBlackboardStoreError {
    if let DbError::TransactionExpectation { step_index, .. } = &error {
        return match *step_index {
            0 => WorkspaceBlackboardStoreError::EditorAccessRequired,
            1 | 2 => WorkspaceBlackboardStoreError::Conflict,
            index if domain_range.contains(&index) => WorkspaceBlackboardStoreError::Conflict,
            _ => WorkspaceBlackboardStoreError::Database(error),
        };
    }
    if error.is_duplicate_key() {
        WorkspaceBlackboardStoreError::Conflict
    } else {
        WorkspaceBlackboardStoreError::Database(error)
    }
}

fn workspace_exists(flavor: DbSqlFlavor, scope: &WorkspaceBlackboardScope) -> DbStatement {
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

fn member_role(
    flavor: DbSqlFlavor,
    scope: &WorkspaceBlackboardScope,
    user_id: &str,
) -> DbStatement {
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

fn post_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceBlackboardScope,
    post_id: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT post_id, tenant_id, project_id, workspace_id, author_actor_id, title, \
             content, status, is_pinned, metadata_json, created_at, updated_at FROM \
             workspace_blackboard_posts WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str());
    if let Some(post_id) = post_id {
        builder = builder.push_static(" AND post_id = ").bind(post_id);
    }
    builder
        .push_static(" ORDER BY is_pinned DESC, created_at DESC, post_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn reply_select(
    flavor: DbSqlFlavor,
    scope: &WorkspaceBlackboardScope,
    post_id: &str,
    reply_id: Option<&str>,
    limit: i64,
    offset: i64,
) -> DbStatement {
    let mut builder = DbStatementBuilder::new(flavor)
        .push_static(
            "SELECT reply_id, tenant_id, project_id, workspace_id, post_id, author_actor_id, \
             content, metadata_json, created_at, updated_at FROM workspace_blackboard_replies \
             WHERE tenant_id = ",
        )
        .bind(scope.tenant_id.as_str())
        .push_static(" AND project_id = ")
        .bind(scope.project_id.as_str())
        .push_static(" AND workspace_id = ")
        .bind(scope.workspace_id.as_str())
        .push_static(" AND post_id = ")
        .bind(post_id);
    if let Some(reply_id) = reply_id {
        builder = builder.push_static(" AND reply_id = ").bind(reply_id);
    }
    builder
        .push_static(" ORDER BY created_at ASC, reply_id ASC LIMIT ")
        .bind(limit)
        .push_static(" OFFSET ")
        .bind(offset)
        .build()
}

fn post_from_row(
    row: &DbRow,
) -> Result<WorkspaceBlackboardPostRecord, WorkspaceBlackboardStoreError> {
    Ok(WorkspaceBlackboardPostRecord {
        post_id: required_string(row, "post_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        author_actor_id: required_string(row, "author_actor_id")?,
        title: required_string(row, "title")?,
        content: required_string(row, "content")?,
        status: required_string(row, "status")?,
        is_pinned: row
            .get_bool("is_pinned")?
            .ok_or(WorkspaceBlackboardStoreError::InvalidRecord("is_pinned"))?,
        metadata: required_json_object(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

fn reply_from_row(
    row: &DbRow,
) -> Result<WorkspaceBlackboardReplyRecord, WorkspaceBlackboardStoreError> {
    Ok(WorkspaceBlackboardReplyRecord {
        reply_id: required_string(row, "reply_id")?,
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        post_id: required_string(row, "post_id")?,
        author_actor_id: required_string(row, "author_actor_id")?,
        content: required_string(row, "content")?,
        metadata: required_json_object(row, "metadata_json")?,
        created_at: required_string(row, "created_at")?,
        updated_at: row.get_string("updated_at")?,
    })
}

pub(super) fn required_string(
    row: &DbRow,
    column: &'static str,
) -> Result<String, WorkspaceBlackboardStoreError> {
    row.get_string(column)?
        .ok_or(WorkspaceBlackboardStoreError::InvalidRecord(column))
}

pub(super) fn required_json_object(
    row: &DbRow,
    column: &'static str,
) -> Result<Value, WorkspaceBlackboardStoreError> {
    let encoded = required_string(row, column)?;
    let value: Value =
        serde_json::from_str(&encoded).map_err(WorkspaceBlackboardStoreError::InvalidJson)?;
    value
        .is_object()
        .then_some(value)
        .ok_or(WorkspaceBlackboardStoreError::InvalidRecord(column))
}
