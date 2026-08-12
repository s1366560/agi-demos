//! Dialect-aware Workspace Agent Policy reads and checked mutations.

use bcs_db_api::{DbCountExpectation, DbError, DbPlugin, DbRow, DbSqlFlavor, DbStatementBuilder};
use memstack_workspace_service_api::WorkspaceScope;
use serde_json::Value;
use thiserror::Error;

use crate::WorkspaceDomainMutation;

/// Scoped Workspace fields required by policy access and default responses.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WorkspacePolicyScopeSnapshot {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub created_by: String,
    pub created_at: String,
    pub updated_at: Option<String>,
}

/// One persisted Workspace Agent Policy.
#[derive(Debug, Clone, PartialEq)]
pub struct WorkspacePolicySnapshot {
    pub tenant_id: String,
    pub project_id: String,
    pub workspace_id: String,
    pub revision: u64,
    pub roles: Value,
    pub fallbacks: Value,
    pub reasoning_effort: String,
    pub permission_mode: String,
    pub updated_at: String,
}

/// Invalid or unavailable policy persistence state.
#[derive(Debug, Error)]
#[non_exhaustive]
pub enum WorkspacePolicyStoreError {
    #[error(transparent)]
    Database(#[from] DbError),

    #[error("Workspace Agent Policy is missing required data: {0}")]
    InvalidField(&'static str),

    #[error("Workspace Agent Policy JSON is invalid: {0}")]
    InvalidJson(#[source] serde_json::Error),

    #[error("Workspace Agent Policy revision is negative")]
    NegativeRevision,
}

/// Read-side and SQL construction helpers for Workspace Agent Policy.
pub struct WorkspacePolicyStore<'a> {
    db: &'a dyn DbPlugin,
    flavor: DbSqlFlavor,
}

impl<'a> WorkspacePolicyStore<'a> {
    #[must_use]
    pub const fn new(db: &'a dyn DbPlugin, flavor: DbSqlFlavor) -> Self {
        Self { db, flavor }
    }

    /// Resolve one active Workspace by its complete public scope.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_scope(
        &self,
        scope: &WorkspaceScope,
    ) -> Result<Option<WorkspacePolicyScopeSnapshot>, WorkspacePolicyStoreError> {
        self.read_scope_statement(
            DbStatementBuilder::new(self.flavor)
                .push_static(
                    "SELECT tenant_id, project_id, workspace_id, created_by, created_at, updated_at \
                     FROM workspace_profiles WHERE tenant_id = ",
                )
                .bind(scope.tenant_id().as_str())
                .push_static(" AND project_id = ")
                .bind(scope.project_id().as_str())
                .push_static(" AND workspace_id = ")
                .bind(scope.workspace_id().as_str())
                .push_static(" AND deleted_at IS NULL")
                .build(),
        )
        .await
    }

    /// Resolve one active Workspace for the legacy project/workspace route.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_scope_by_project(
        &self,
        project_id: &str,
        workspace_id: &str,
    ) -> Result<Option<WorkspacePolicyScopeSnapshot>, WorkspacePolicyStoreError> {
        self.read_scope_statement(
            DbStatementBuilder::new(self.flavor)
                .push_static(
                    "SELECT tenant_id, project_id, workspace_id, created_by, created_at, updated_at \
                     FROM workspace_profiles WHERE project_id = ",
                )
                .bind(project_id)
                .push_static(" AND workspace_id = ")
                .bind(workspace_id)
                .push_static(" AND deleted_at IS NULL")
                .build(),
        )
        .await
    }

    /// Check legacy read or manager access without consulting old Workspace tables.
    ///
    /// # Errors
    ///
    /// Returns a database error when the normalized ACL projections cannot be read.
    pub async fn has_access(
        &self,
        scope: &WorkspaceScope,
        actor_id: &str,
        require_manager: bool,
    ) -> Result<bool, WorkspacePolicyStoreError> {
        let workspace_roles = if require_manager {
            " AND role IN ('owner', 'editor')"
        } else {
            ""
        };
        let project_roles = if require_manager {
            " AND role IN ('owner', 'admin')"
        } else {
            ""
        };
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static("SELECT 1 AS allowed FROM workspace_profiles p WHERE p.tenant_id = ")
            .bind(scope.tenant_id().as_str())
            .push_static(" AND p.project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND p.workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .push_static(" AND p.deleted_at IS NULL AND (p.created_by = ")
            .bind(actor_id)
            .push_static(
                " OR EXISTS (SELECT 1 FROM workspace_members WHERE tenant_id = p.tenant_id \
                 AND project_id = p.project_id AND workspace_id = p.workspace_id AND user_id = ",
            )
            .bind(actor_id)
            .push_static(workspace_roles)
            .push_static(
                ") OR EXISTS (SELECT 1 FROM project_principal_memberships WHERE tenant_id = \
                 p.tenant_id AND project_id = p.project_id AND user_id = ",
            )
            .bind(actor_id)
            .push_static(" AND is_active = TRUE")
            .push_static(project_roles)
            .push_static(")) LIMIT 1")
            .build();
        Ok(!self.db.query(statement).await?.is_empty())
    }

    /// Read the current policy row for one scoped Workspace.
    ///
    /// # Errors
    ///
    /// Returns a database or row-decoding error.
    pub async fn read_policy(
        &self,
        scope: &WorkspaceScope,
    ) -> Result<Option<WorkspacePolicySnapshot>, WorkspacePolicyStoreError> {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "SELECT tenant_id, project_id, workspace_id, revision, roles_json, fallbacks_json, \
                 reasoning_effort, permission_mode, updated_at FROM workspace_agent_policies \
                 WHERE tenant_id = ",
            )
            .bind(scope.tenant_id().as_str())
            .push_static(" AND project_id = ")
            .bind(scope.project_id().as_str())
            .push_static(" AND workspace_id = ")
            .bind(scope.workspace_id().as_str())
            .build();
        let rows = self.db.query(statement).await?;
        rows.first().map(policy_from_row).transpose()
    }

    /// Build an insert-or-CAS-update checked against the public policy revision.
    #[must_use]
    pub fn upsert_mutation(
        &self,
        snapshot: &WorkspacePolicySnapshot,
        expected_policy_revision: u64,
        updated_by: &str,
    ) -> WorkspaceDomainMutation {
        let statement = DbStatementBuilder::new(self.flavor)
            .push_static(
                "INSERT INTO workspace_agent_policies (workspace_id, tenant_id, project_id, \
                 revision, roles_json, fallbacks_json, reasoning_effort, permission_mode, \
                 updated_by, created_at, updated_at) SELECT ",
            )
            .bind(snapshot.workspace_id.as_str())
            .push_static(", ")
            .bind(snapshot.tenant_id.as_str())
            .push_static(", ")
            .bind(snapshot.project_id.as_str())
            .push_static(", ")
            .bind(snapshot.revision)
            .push_static(", ")
            .bind(snapshot.roles.to_string())
            .push_static(", ")
            .bind(snapshot.fallbacks.to_string())
            .push_static(", ")
            .bind(snapshot.reasoning_effort.as_str())
            .push_static(", ")
            .bind(snapshot.permission_mode.as_str())
            .push_static(", ")
            .bind(updated_by)
            .push_static(", ")
            .bind(snapshot.updated_at.as_str())
            .push_static(", ")
            .bind(snapshot.updated_at.as_str())
            .push_static(" WHERE ")
            .bind(expected_policy_revision)
            .push_static(
                " = 0 OR EXISTS (SELECT 1 FROM workspace_agent_policies WHERE workspace_id = ",
            )
            .bind(snapshot.workspace_id.as_str())
            .push_static(" AND tenant_id = ")
            .bind(snapshot.tenant_id.as_str())
            .push_static(" AND project_id = ")
            .bind(snapshot.project_id.as_str())
            .push_static(
                ") ON CONFLICT(workspace_id) DO UPDATE SET revision = excluded.revision, \
                 roles_json = excluded.roles_json, fallbacks_json = excluded.fallbacks_json, \
                 reasoning_effort = excluded.reasoning_effort, \
                 permission_mode = excluded.permission_mode, updated_by = excluded.updated_by, \
                 updated_at = excluded.updated_at WHERE workspace_agent_policies.tenant_id = \
                 excluded.tenant_id AND workspace_agent_policies.project_id = excluded.project_id \
                 AND workspace_agent_policies.revision = ",
            )
            .bind(expected_policy_revision)
            .build();
        WorkspaceDomainMutation::new(statement, DbCountExpectation::exactly(1))
    }

    async fn read_scope_statement(
        &self,
        statement: bcs_db_api::DbStatement,
    ) -> Result<Option<WorkspacePolicyScopeSnapshot>, WorkspacePolicyStoreError> {
        let rows = self.db.query(statement).await?;
        rows.first().map(scope_from_row).transpose()
    }
}

fn scope_from_row(row: &DbRow) -> Result<WorkspacePolicyScopeSnapshot, WorkspacePolicyStoreError> {
    Ok(WorkspacePolicyScopeSnapshot {
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        created_by: required_string(row, "created_by")?,
        created_at: required_string(row, "created_at")?,
        updated_at: optional_string(row, "updated_at")?,
    })
}

fn policy_from_row(row: &DbRow) -> Result<WorkspacePolicySnapshot, WorkspacePolicyStoreError> {
    let revision = required_i64(row, "revision")?;
    Ok(WorkspacePolicySnapshot {
        tenant_id: required_string(row, "tenant_id")?,
        project_id: required_string(row, "project_id")?,
        workspace_id: required_string(row, "workspace_id")?,
        revision: u64::try_from(revision)
            .map_err(|_| WorkspacePolicyStoreError::NegativeRevision)?,
        roles: required_json(row, "roles_json")?,
        fallbacks: required_json(row, "fallbacks_json")?,
        reasoning_effort: required_string(row, "reasoning_effort")?,
        permission_mode: required_string(row, "permission_mode")?,
        updated_at: required_string(row, "updated_at")?,
    })
}

fn required_string(row: &DbRow, column: &'static str) -> Result<String, WorkspacePolicyStoreError> {
    row.get_string(column)?
        .ok_or(WorkspacePolicyStoreError::InvalidField(column))
}

fn optional_string(
    row: &DbRow,
    column: &'static str,
) -> Result<Option<String>, WorkspacePolicyStoreError> {
    row.get_string(column)
        .map_err(WorkspacePolicyStoreError::Database)
}

fn required_i64(row: &DbRow, column: &'static str) -> Result<i64, WorkspacePolicyStoreError> {
    row.get_i64(column)?
        .ok_or(WorkspacePolicyStoreError::InvalidField(column))
}

fn required_json(row: &DbRow, column: &'static str) -> Result<Value, WorkspacePolicyStoreError> {
    let value = required_string(row, column)?;
    serde_json::from_str(&value).map_err(WorkspacePolicyStoreError::InvalidJson)
}
